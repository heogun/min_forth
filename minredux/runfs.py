#!/usr/bin/env python3
"""Run a Forth source file on the minforth kernel over UART.

The MinOS line editor only accepts short lines, so strip comment lines and
re-wrap the remaining tokens at <=46 characters before feeding them.
"""
import subprocess, sys, textwrap, os

MAX = 46

def wrap_source(path):
    tokens = []
    for line in open(path, encoding="utf-8"):
        line = line.split("\\", 1)[0]
        line = line.strip()
        if not line:
            continue
        tokens.extend(line.split())
    lines, cur = [], ""
    for tok in tokens:
        if not cur:
            cur = tok
        elif len(cur) + 1 + len(tok) <= MAX:
            cur += " " + tok
        else:
            lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines

def main():
    if len(sys.argv) < 2:
        print("usage: runfs.py FILE.fs [extra minredux args...]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    extra = sys.argv[2:]
    lines = wrap_source(path)
    payload = "minforth\n" + "\n".join(lines) + "\n"
    h = payload.encode().hex()
    cmd = [
        "./target/release/minredux", "run",
        "--rom-dir", "../minforth/build",
        "--uart-hex", h, "--uart-after", "200000",
        "--stats",
    ] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout, end="")
    if r.stderr:
        print(r.stderr, end="", file=sys.stderr)
    return r.returncode

if __name__ == "__main__":
    raise SystemExit(main())
