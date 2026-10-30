#!/usr/bin/env python3
"""Insert/replace a file in a Minimal 64x4 Redux FLASH filesystem image.

Filesystem layout (little-endian 16-bit fields):

    20 bytes  name, NUL padded
     2 bytes  destination RAM address
     2 bytes  size in bytes
     N bytes  contents

Entries start at FLASH offset 0x2000 and are packed back to back.  A
0xff byte in the name field marks the end of the used area.

Usage:
    fspatch.py <flash.bin> <out.bin> <name> <dest> <datafile>

`dest` is a hex address such as 0x1000.  If <name> already exists its data
is replaced in place as long as the new payload is no larger; otherwise the
entry is appended.  Existing entries are compacted so no gaps are left.
"""

import sys

FS_START = 0x2000
HEADER = 24
NAME_LEN = 20
VISIBLE = 0  # first name byte 0xff terminates, 0 means hidden


def parse(fs: bytes):
    entries = []
    a = FS_START
    while a + HEADER <= len(fs):
        if fs[a] == 0xFF:
            break
        name = fs[a : a + NAME_LEN].split(b"\0")[0]
        dest = fs[a + 20] | (fs[a + 21] << 8)
        size = fs[a + 22] | (fs[a + 23] << 8)
        data = fs[a + HEADER : a + HEADER + size]
        if len(data) != size:
            raise ValueError(f"truncated entry at 0x{a:05x}")
        entries.append([name, dest, data])
        a += HEADER + size
        if size == 0:
            raise ValueError(f"zero-size entry at 0x{a:05x}")
    return entries, a


def build(entries):
    out = bytearray()
    for name, dest, data in entries:
        hdr = bytearray(HEADER)
        hdr[0 : len(name)] = name[:NAME_LEN]
        hdr[20] = dest & 0xFF
        hdr[21] = (dest >> 8) & 0xFF
        hdr[22] = len(data) & 0xFF
        hdr[23] = (len(data) >> 8) & 0xFF
        out += hdr
        out += data
    return bytes(out)


def main():
    if len(sys.argv) != 6:
        print(__doc__)
        return 2
    src, dst, name, dest_s, datafile = sys.argv[1:]
    name_b = name.encode()
    if len(name_b) > NAME_LEN:
        raise SystemExit("name too long")
    dest = int(dest_s, 0)
    data = open(datafile, "rb").read()

    image = bytearray(open(src, "rb").read())
    entries, used_end = parse(image)

    replaced = False
    for e in entries:
        if e[0] == name_b:
            e[1] = dest
            e[2] = data
            replaced = True
            break
    if not replaced:
        entries.append([name_b, dest, data])

    payload = build(entries)
    payload_end = FS_START + len(payload)
    # Everything from the end of the filesystem onwards is preserved.
    tail = bytearray(image[used_end:]) if used_end < len(image) else bytearray()
    # Keep the previous contents of the image beyond the entries untouched.
    image[FS_START:payload_end] = payload
    if payload_end < used_end:
        image[payload_end:used_end] = b"\xff" * (used_end - payload_end)
    open(dst, "wb").write(image)

    total = sum(len(e[2]) for e in entries)
    print(
        f"{dst}: {len(entries)} files, {total} data bytes, fs ends 0x{payload_end:05x}"
    )
    for n, d, b in entries:
        print(f"  {n.decode('latin1'):20} dest=0x{d:04x} size={len(b)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
