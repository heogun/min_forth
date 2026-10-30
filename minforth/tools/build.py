#!/usr/bin/env python3
"""Build a Minimal 64x4 Redux program and drop it into a copy of flash.bin.

    build.py <source.fs|.asm> <name> <dest> [--out DIR]

The source is run through a small preprocessor (see preprocess()), assembled
with slu4's assembler, converted to a flat binary and inserted into the flash
filesystem.  The result is an image directory that can be handed to the
emulator via `--rom-dir`.
"""

import os
import json
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
ASM = os.path.join(ROOT, "tools", "asm")
ROM = os.path.join(REPO, "minimal64", "Revision 1.4 Redux", "FLASH Images")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import hex2bin  # noqa: E402
import fspatch  # noqa: E402


# ----------------------------------------------------------------------------
# Preprocessor
# ----------------------------------------------------------------------------

MACROS = {}


class _Ctx:
    def __init__(self, path):
        self.path = path
        self.uid = 0

    def unique(self):
        self.uid += 1
        return f"{self.uid}"


def _strip_comment(text):
    """Remove a trailing ; comment, respecting double-quoted strings."""
    out = []
    inq = False
    for ch in text:
        if ch == '"':
            inq = not inq
        if ch == ";" and not inq:
            break
        out.append(ch)
    return "".join(out)


def _expand_macro(name, argtext, ctx):
    """Expand one macro invocation into text."""
    argtext = _strip_comment(argtext)
    nargs, body = MACROS[name]
    # split arguments respecting quoted strings and nested <>
    args = []
    cur = ""
    inq = None
    for ch in argtext:
        if inq:
            cur += ch
            if ch == inq:
                inq = None
        elif ch in "\"'":
            cur += ch
            inq = ch
        elif ch.isspace():
            if cur:
                args.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        args.append(cur)
    if nargs >= 0 and len(args) != nargs:
        if not (nargs == 0 and not args):
            raise RuntimeError(
                f"{ctx.path}: macro {name} expects {nargs} args, got {len(args)}: {argtext!r}"
            )
    uid = ctx.unique()
    out = body
    for i, a in enumerate(args):
        out = out.replace("${%d}" % (i + 1), a)
    out = out.replace("${__}", uid)
    return out


def preprocess(path, defines=None, depth=0):
    if depth > 32:
        raise RuntimeError("include depth exceeded")
    defines = dict(defines or {})
    root = os.path.dirname(os.path.abspath(path))
    ctx = _Ctx(path)
    out = []
    # stack of (active, taken)
    cond = []
    lines = open(path).read().split("\n")
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        idx += 1
        line = raw.rstrip("\n")
        st = line.strip()
        if not st:
            out.append(line)
            continue
        if st.startswith("%"):
            parts = st[1:].split(None, 1)
            if not parts:
                continue
            cmd, rest = parts[0], (parts[1] if len(parts) > 1 else "")
            if cmd in ("ifdef", "ifndef", "ifeq", "ifne"):
                active = all(a for a, _ in cond)
                if cmd == "ifdef":
                    taken = rest in defines
                elif cmd == "ifndef":
                    taken = rest not in defines
                elif cmd == "ifeq":
                    k, _, v = rest.partition(",")
                    taken = defines.get(k.strip(), "") == v.strip()
                else:
                    k, _, v = rest.partition(",")
                    taken = defines.get(k.strip(), "") != v.strip()
                cond.append((active and taken, taken))
                continue
            if cmd == "else":
                if not cond:
                    raise RuntimeError(f"{path}:{idx}: stray %else")
                parent = all(a for a, _ in cond[:-1])
                active, taken = cond.pop()
                cond.append((parent and not taken, True))
                continue
            if cmd == "endif":
                if not cond:
                    raise RuntimeError(f"{path}:{idx}: stray %endif")
                cond.pop()
                continue
            if not all(a for a, _ in cond):
                continue
            if cmd == "define":
                name, _, value = rest.partition(" ")
                defines[name] = value.strip()
            elif cmd == "undef":
                defines.pop(rest.strip(), None)
            elif cmd == "include":
                target = rest.strip().strip('"').strip("'")
                sub = os.path.join(root, target)
                out.append(preprocess(sub, defines, depth + 1).rstrip("\n"))
            elif cmd == "macro":
                if " " in rest:
                    mname, nargs = rest.split()
                    nargs = int(nargs)
                else:
                    mname, nargs = rest, -1
                body = []
                while idx < len(lines):
                    if lines[idx].strip() == "%endmacro":
                        idx += 1
                        break
                    body.append(lines[idx])
                    idx += 1
                else:
                    raise RuntimeError(f"{path}: unterminated %macro {mname}")
                MACROS[mname] = (nargs, "\n".join(body))
            else:
                raise RuntimeError(f"{path}:{idx}: unknown directive %{cmd}")
            continue
        if not all(a for a, _ in cond):
            continue
        # macro invocation at the start of a line (optionally after a label)
        indent = line[: len(line) - len(line.lstrip())]
        head = ""
        rest = st
        first = rest.split(None, 1)[0]
        if first.endswith(":") and " " in rest:
            head = first + " "
            rest = rest.split(None, 1)[1]
            first = rest.split(None, 1)[0]
        if first in MACROS:
            argtext = rest[len(first):]
            out.append(indent + head + _expand_macro(first, argtext, ctx))
            continue
        # simple ${NAME} substitution
        if "${" in line:
            for k, v in defines.items():
                line = line.replace("${%s}" % k, v)
        out.append(line)
    if cond:
        raise RuntimeError(f"{path}: unterminated %if")
    return "\n".join(out) + "\n"



def assemble(source_text, symbols=None, emitted=None):
    with tempfile.NamedTemporaryFile("w", suffix=".asm", delete=False) as f:
        f.write(source_text)
        src = f.name
    try:
        r = subprocess.run([ASM, src], capture_output=True, text=True)
        if symbols is not None and r.returncode == 0 and "ERROR" not in r.stdout:
            s = subprocess.run([ASM, src, "-s"], capture_output=True, text=True, check=True)
            if "ERROR" in s.stdout:
                raise RuntimeError("symbol assembly failed:\n" + s.stdout)
            symbols.update({name: int(value, 16) for value, name in
                            re.findall(r"^#org 0x([0-9a-fA-F]{4}) ([^:\s]+):$", s.stdout, re.M)})
            if not symbols:
                raise RuntimeError("assembler returned no symbols")
    finally:
        os.unlink(src)
    if r.returncode != 0 or "ERROR" in r.stdout:
        raise SystemExit("assembly failed:\n" + (r.stdout + r.stderr))
    with tempfile.NamedTemporaryFile("w", suffix=".hex", delete=False) as f:
        f.write(r.stdout)
        hexf = f.name
    try:
        mem = hex2bin.load_hex(hexf)
    finally:
        os.unlink(hexf)
    if emitted is not None:
        emitted.update(mem)
    lo = min(mem)
    hi = max(mem)
    return bytes(mem.get(a, 0xFF) for a in range(lo, hi + 1)), lo


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__)
        return 2
    src, name, dest_s = args[0], args[1], args[2]
    outdir = os.path.join(ROOT, "build")
    i = 3
    while i < len(args):
        if args[i] == "--out":
            outdir = args[i + 1]
            i += 2
        elif args[i] == "--define":
            i += 2  # handled below
        else:
            raise SystemExit(f"unknown option {args[i]}")
    defines = {}
    i = 3
    while i < len(args):
        if args[i] == "--out":
            i += 2
        elif args[i] == "--define":
            k, _, v = args[i + 1].partition("=")
            defines[k] = v
            i += 2
        else:
            i += 1

    # Always prepend the standard symbol table.  Sources must start with an
    # explicit #org after this point (defs.inc leaves pc in the 0xf0xx range).
    defs = os.path.join(ROOT, "forth", "defs.inc")
    define_syms = preprocess(defs, defines)
    body = preprocess(src, defines)
    org = re.search(r"^\s*#org\s", body, re.M)
    if not org:
        raise SystemExit(f"{src}: source must contain an explicit #org")
    text = define_syms + "\n" + body[org.start():]
    symbols = {}
    binary, base = assemble(text, symbols)
    dest = int(dest_s, 0)
    if base != dest:
        raise SystemExit(f"source assembles at 0x{base:04x}, expected 0x{dest:04x}")

    os.makedirs(outdir, exist_ok=True)
    tmpbin = os.path.join(outdir, name + ".bin")
    open(tmpbin, "wb").write(binary)
    with open(os.path.join(outdir, name + ".symbols.json"), "w") as f:
        json.dump(symbols, f, indent=2, sort_keys=True)
        f.write("\n")
    for f in ("ctrl_lsb.bin", "ctrl_msb.bin", "ctrl_hsb.bin"):
        shutil.copyfile(os.path.join(ROM, f), os.path.join(outdir, f))
    flash_out = os.path.join(outdir, "flash.bin")
    if not os.path.exists(flash_out):
        shutil.copyfile(os.path.join(ROM, "flash.bin"), flash_out)
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        sys.argv = ["fspatch", flash_out, flash_out, name, hex(dest), tmpbin]
        fspatch.main()
    print(f"built {name}: {len(binary)} bytes at 0x{dest:04x} -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
