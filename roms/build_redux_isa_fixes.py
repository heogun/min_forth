#!/usr/bin/env python3
"""Rebuild a separate Redux 1.4 control-ROM bundle; never edit the reference.

    python3 roms/build_redux_isa_fixes.py
    python3 roms/build_redux_isa_fixes.py --check

Use --out for another output directory and --flash for a different program
FLASH (for example minforth/build/flash.bin). Existing differing files are
never overwritten. No assembler or third-party Python packages are required.
"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "minimal64" / "Revision 1.4 Redux"
VERSION = "redux-1.4-isa-fixes-v1"
DEFAULT_OUT = ROOT / "roms" / VERSION
INVERT_MASK = 0xEBFAF9
SIGNALS = {name: 1 << i for i, name in enumerate(
    "BO EC ES EO IC II FI IO MC CIH CE BI AI AO COH COL MIL MIH ME CIL MZ RO NI RI".split()
)}
REFERENCE_HASHES = {
    "ctrl_lsb.bin": "d056f45db6da4c67d5b843cd49ec19879ac286204d036e34dd4ac68e6928ec34",
    "ctrl_msb.bin": "3b04671b89b859f84e9043e0fd6e5af015102241bad7318119154030e8db0f40",
    "ctrl_hsb.bin": "d10100d6d9c7bb87c599fce032d4d39f7f75e5d4a4adefdc425b978c33864ad1",
}
# Changes are expressed as logical signals, before active-low ROM inversion.
# Retaining the old slots preserves the XOR instruction lengths in clocks.
EDITS = {
    "XR_B": {
        5: ("FF|MIL|MZ|MIH", "FF"),
        9: ("EO|ES|EC|AI|MC|MIL|MIH|IC", "EO|ES|EC|AI|RI|MC|MIL|MIH|IC"),
    },
    "XR_R": {8: ("FF|MIL|MZ|MIH", "FF")},
    "WINx11x0xx": {1: ("FF|BI|FI", "FF|BI")},
    "WINx11x1xx": {1: ("FF|BI|FI", "FF|BI")},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_definitions(data):
    definitions = {}
    for line in data.decode("utf-8").splitlines():
        if not line.startswith("#define "):
            continue
        _, name, body = line.split(None, 2)
        words = [word.strip() for word in body.split(",")]
        if len(words) != 16 or name in definitions:
            raise ValueError(f"invalid definition: {name}")
        definitions[name] = words
    return definitions


def edit_definitions(data):
    found = set()
    lines = []
    for line in data.decode("utf-8").splitlines(keepends=True):
        if line.startswith("#define "):
            _, name, body = line.split(None, 2)
            if name in EDITS:
                words = [word.strip() for word in body.split(",")]
                for step, (before, after) in EDITS[name].items():
                    if words[step] != before:
                        raise ValueError(f"unexpected source word: {name}[{step}]")
                    words[step] = after
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                line = f"#define {name} " + ", ".join(words) + newline
                found.add(name)
        lines.append(line)
    if found != set(EDITS):
        raise ValueError("missing microcode definitions to patch")
    return "".join(lines).encode("utf-8")


def compile_rom(definition_data, mapping_data):
    definitions = parse_definitions(definition_data)
    rows = []
    for line in mapping_data.decode("utf-8").splitlines():
        row = [name.strip() for name in line.split("*/", 1)[1].split(",") if name.strip()]
        if len(row) != 256:
            raise ValueError("mapping row must have 256 opcodes")
        rows.append(row)
    if len(rows) != 128:
        raise ValueError("mapping must have 128 flag rows")
    rom = [bytearray() for _ in range(3)]
    for row in rows:
        for name in row:
            for word in definitions[name]:
                logical = 0
                for signal in word.split("|"):
                    if signal not in ("FF", "0"):
                        logical |= SIGNALS[signal]
                raw = logical ^ INVERT_MASK
                for i, image in enumerate(rom):
                    image.append((raw >> (8 * i)) & 0xFF)
    return dict(zip(REFERENCE_HASHES, map(bytes, rom)))


def build_bundle(flash_path):
    definition_data = (SOURCE / "microcode_def.csv").read_bytes()
    mapping_data = (SOURCE / "microcode_rom.csv").read_bytes()
    reference = {name: (SOURCE / "FLASH Images" / name).read_bytes() for name in REFERENCE_HASHES}
    for name, data in reference.items():
        if digest(data) != REFERENCE_HASHES[name]:
            raise ValueError(f"reference ROM hash changed: {name}; review before rebuilding")
    if compile_rom(definition_data, mapping_data) != reference:
        raise ValueError("source CSVs do not reproduce the reference ROMs")
    patched_definitions = edit_definitions(definition_data)
    images = compile_rom(patched_definitions, mapping_data)
    # Only the three reviewed opcodes in running (R=1) flag rows may change.
    changes = []
    allowed = {0x04: {1}, 0x52: {5, 9}, 0x54: {8}}
    for index in range(0x80000):
        before = sum(reference[name][index] << (8 * i) for i, name in enumerate(reference))
        after = sum(images[name][index] << (8 * i) for i, name in enumerate(images))
        if before == after:
            continue
        flags, opcode, step = index >> 12, (index >> 4) & 255, index & 15
        if not flags & 0x40 or step not in allowed.get(opcode, set()):
            raise ValueError(f"unintended control-word change at {index:05x}")
        changes.append({"index": index, "flags": flags, "opcode": opcode, "step": step,
                        "before_logical": before ^ INVERT_MASK, "after_logical": after ^ INVERT_MASK})
    if len(changes) != 208:
        raise ValueError(f"expected 208 changed control words, got {len(changes)}")
    flash = flash_path.read_bytes()
    if len(flash) != 0x80000:
        raise ValueError("program FLASH must be exactly 512 KiB")
    payloads = {
        **images,
        "flash.bin": flash,
        "microcode_def.csv": patched_definitions,
        "microcode_rom.csv": mapping_data,
    }
    manifest = {
        "version": VERSION,
        "source_directory": "minimal64/Revision 1.4 Redux",
        "reference_control_rom_sha256": REFERENCE_HASHES,
        "reference_csv_sha256": {"microcode_def.csv": digest(definition_data), "microcode_rom.csv": digest(mapping_data)},
        "program_flash_sha256": digest(flash),
        "program_flash_is_reference": flash == (SOURCE / "FLASH Images" / "flash.bin").read_bytes(),
        "outputs": {name: {"bytes": len(data), "sha256": digest(data)} for name, data in payloads.items()},
        "changed_bytes": {name: sum(a != b for a, b in zip(reference[name], images[name])) for name in reference},
        "changed_control_words": changes,
        "fixes": ["XR.B destination writeback (10 clocks)", "XR.R destination writeback (13 clocks)",
                  "WIN: sample I/O readiness at the low-byte decrement, not before it"],
        "hardware_timing_validated": False,
    }
    payloads["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return payloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--flash", type=Path, default=SOURCE / "FLASH Images" / "flash.bin")
    parser.add_argument("--check", action="store_true", help="verify existing bundle without writing")
    args = parser.parse_args()
    out = args.out.resolve()
    if out == SOURCE.resolve() or SOURCE.resolve() in out.parents:
        parser.error("output must not be inside the original Redux reference directory")
    payloads = build_bundle(args.flash)
    # Validate every existing destination before writing any file. In particular,
    # never follow file symlinks into the reference images or overwrite user edits.
    for name, data in payloads.items():
        path = out / name
        if path.is_symlink():
            parser.error(f"refusing symlink destination: {path}")
        if path.exists() and path.read_bytes() != data:
            parser.error(f"refusing to overwrite differing file: {path}")
        if args.check and not path.is_file():
            parser.error(f"missing generated file: {path}")
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            path = out / name
            if not path.exists():
                path.write_bytes(data)
    print(f"{'verified' if args.check else 'saved'} {VERSION}: {out}")
    print("control-word changes=208; byte changes: lsb=16, msb=0, hsb=192; original images untouched")


if __name__ == "__main__":
    main()
