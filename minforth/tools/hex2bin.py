#!/usr/bin/env python3
"""Convert the slu4 assembler's Intel HEX output into a flat binary.

The Minimal 64x4 assembler emits absolute FLASH addresses, so the output is a
single contiguous image covering [min address, max address].  Gaps are filled
with 0xff, matching erased FLASH.

Usage: hex2bin.py <in.hex> <out.bin> [--base N] [--pad N]
"""

import sys


def load_hex(path):
    mem = {}
    for raw in open(path):
        line = raw.strip()
        if not line.startswith(":"):
            continue
        b = bytes.fromhex(line[1:])
        n, addr, typ = b[0], (b[1] << 8) | b[2], b[3]
        if typ == 0:
            for i in range(n):
                mem[addr + i] = b[4 + i]
        elif typ == 1:
            break
        else:
            raise ValueError(f"unsupported record type {typ}")
    return mem


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    src, dst = args[0], args[1]
    base = None
    pad = 0xFF
    i = 2
    while i < len(args):
        if args[i] == "--base":
            base = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--pad":
            pad = int(args[i + 1], 0)
            i += 2
        else:
            raise SystemExit(f"unknown option {args[i]}")

    mem = load_hex(src)
    if not mem:
        raise SystemExit("no data in hex file")
    lo = base if base is not None else min(mem)
    hi = max(mem)
    if lo > hi:
        raise SystemExit("base beyond emitted data")
    out = bytearray([pad]) * (hi - lo + 1)
    for a, v in mem.items():
        out[a - lo] = v
    open(dst, "wb").write(out)
    print(f"{dst}: 0x{lo:04x}..0x{hi:04x} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
