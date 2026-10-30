#!/usr/bin/env python3
"""Verify the corrected ROMs installed at the project's primary ROM path.

No original-ROM directory or deleted bundle/generator is needed. --write-images
explicitly regenerates only the corrected control images from the current CSVs;
unknown existing images are never overwritten, and program FLASH is never written.
"""
import argparse
import hashlib
from pathlib import Path

REDUX = Path(__file__).resolve().parents[1] / "minimal64/Revision 1.4 Redux"
SIGNALS = {name: 1 << bit for bit, name in enumerate(
    "BO EC ES EO IC II FI IO MC CIH CE BI AI AO COH COL MIL MIH ME CIL MZ RO NI RI".split())}
CORRECTED_SHA256 = {
    "ctrl_lsb.bin": "a3e8c3b2d84ce2bc07ac545450ff930c24a4064e7da61f048ab590b885d4abbd",
    "ctrl_msb.bin": "3b04671b89b859f84e9043e0fd6e5af015102241bad7318119154030e8db0f40",
    "ctrl_hsb.bin": "94e6179d5c378260c34abd424f9328de438fe94025267cc73fd26e428bf679ca",
}
# Migration guards only; old ROMs are neither restored nor executed.
PRE_FIX_SHA256 = {
    "ctrl_lsb.bin": "d056f45db6da4c67d5b843cd49ec19879ac286204d036e34dd4ac68e6928ec34",
    "ctrl_msb.bin": CORRECTED_SHA256["ctrl_msb.bin"],
    "ctrl_hsb.bin": "d10100d6d9c7bb87c599fce032d4d39f7f75e5d4a4adefdc425b978c33864ad1",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compile_images(root=REDUX):
    definitions = {}
    for line in (root / "microcode_def.csv").read_text().splitlines():
        if not line.startswith("#define "):
            continue
        _, name, body = line.split(None, 2)
        words = []
        for expression in body.split(","):
            logical = 0
            for signal in expression.strip().split("|"):
                if signal not in ("FF", "0"):
                    logical |= SIGNALS[signal]
            words.append(logical ^ 0xEBFAF9)
        if len(words) != 16 or name in definitions:
            raise ValueError(f"invalid definition: {name}")
        definitions[name] = words
    rows = []
    for line in (root / "microcode_rom.csv").read_text().splitlines():
        row = [name.strip() for name in line.split("*/", 1)[1].split(",") if name.strip()]
        if len(row) != 256:
            raise ValueError("expected 256 opcode entries per flag row")
        rows.append(row)
    if len(rows) != 128:
        raise ValueError("expected 128 flag rows")
    images = [bytearray() for _ in range(3)]
    for row in rows:
        for name in row:
            for word in definitions[name]:
                for lane, image in enumerate(images):
                    image.append((word >> (lane * 8)) & 255)
    return dict(zip(CORRECTED_SHA256, map(bytes, images)))


def verify(root=REDUX, write=False):
    images = compile_images(root)
    for name, data in images.items():
        if sha(data) != CORRECTED_SHA256[name]:
            raise ValueError(f"CSV does not generate the reviewed corrected ROM: {name}")
        path = root / "FLASH Images" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"expected regular existing image: {path}")
        current_hash = sha(path.read_bytes())
        allowed = {CORRECTED_SHA256[name], PRE_FIX_SHA256[name]} if write else {CORRECTED_SHA256[name]}
        if current_hash not in allowed:
            raise ValueError(f"image is not the reviewed corrected ROM (or migration source): {name}")
    if write:
        for name, data in images.items():
            path = root / "FLASH Images" / name
            if path.read_bytes() != data:
                path.write_bytes(data)
    for name, data in images.items():
        if (root / "FLASH Images" / name).read_bytes() != data:
            raise ValueError(f"CSV/image mismatch: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-images", action="store_true")
    args = parser.parse_args()
    try:
        verify(write=args.write_images)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"ROM verification failed: {error}\n")
    print("Verified corrected primary ROMs: CSV + SHA-256, all 524288 control words.")


if __name__ == "__main__":
    main()
