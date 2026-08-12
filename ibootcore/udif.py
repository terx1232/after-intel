#!/usr/bin/env python3
"""
udif.py -- flatten an Apple UDIF disk image (.dmg) into a raw disk.

The decrypted BaseSystem is a UDIF image: a data fork, an XML plist holding the
`blkx` block map, and a `koly` trailer. The kernel's ramdisk path wants a flat
disk it can hand to a media device, so the map has to be replayed - the stored
data covers only the allocated runs, and the unallocated ones are zero-fill that
was never written down.

Chunk types follow Apple's list: 0 and 2 are zero/ignore, 1 is raw, 0x80000005
zlib, 0x80000006 bzip2, 0x80000007 lzfse, 0x80000008 lzma, 0xffffffff ends the
map.

Usage:
    python udif.py BaseSystem.dmg --list
    python udif.py BaseSystem.dmg --out BaseSystem.img
"""

from __future__ import annotations

import argparse
import base64
import plistlib
import struct
import sys

SECTOR = 512

ZERO = 0x00000000
RAW = 0x00000001
IGNORE = 0x00000002
ZLIB = 0x80000005
BZIP2 = 0x80000006
LZFSE = 0x80000007
LZMA = 0x80000008
END = 0xFFFFFFFF

NAMES = {ZERO: "zero", RAW: "raw", IGNORE: "ignore", ZLIB: "zlib",
         BZIP2: "bzip2", LZFSE: "lzfse", LZMA: "lzma", END: "end"}


def read_trailer(fh, size: int):
    fh.seek(size - 512)
    t = fh.read(512)
    if t[:4] != b"koly":
        raise ValueError("no koly trailer: not a UDIF image")
    data_off, data_len = struct.unpack_from(">QQ", t, 24)
    xml_off, xml_len = struct.unpack_from(">QQ", t, 0xD8)
    return data_off, data_len, xml_off, xml_len


def chunks(mish: bytes):
    if mish[:4] != b"mish":
        return
    start_sector, sector_count = struct.unpack_from(">QQ", mish, 8)
    n = struct.unpack_from(">I", mish, 0xC8)[0]
    for i in range(n):
        off = 0xCC + i * 40
        kind, _, sec, cnt, coff, clen = struct.unpack_from(">IIQQQQ", mish, off)
        yield kind, start_sector + sec, cnt, coff, clen


def decode(kind: int, blob: bytes, want: int) -> bytes:
    if kind in (ZERO, IGNORE):
        return b"\x00" * want
    if kind == RAW:
        return blob
    if kind == ZLIB:
        import zlib
        return zlib.decompress(blob)
    if kind == BZIP2:
        import bz2
        return bz2.decompress(blob)
    if kind == LZFSE:
        import liblzfse
        return liblzfse.decompress(blob)
    if kind == LZMA:
        import lzma
        return lzma.decompress(blob)
    raise ValueError(f"unsupported chunk type {kind:#x}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    import os
    size = os.path.getsize(args.image)
    fh = open(args.image, "rb")
    data_off, data_len, xml_off, xml_len = read_trailer(fh, size)

    fh.seek(xml_off)
    plist = plistlib.loads(fh.read(xml_len))
    blkx = plist["resource-fork"]["blkx"]

    total = 0
    kinds = {}
    parts = []
    for entry in blkx:
        mish = entry["Data"] if isinstance(entry["Data"], bytes) \
            else base64.b64decode(entry["Data"])
        parts.append((entry.get("Name", ""), mish))
        for kind, sec, cnt, coff, clen in chunks(mish):
            if kind == END:
                continue
            kinds[kind] = kinds.get(kind, 0) + cnt
            total = max(total, sec + cnt)

    print(f"\n  data fork {data_len:,} bytes, {len(blkx)} blkx entries")
    print(f"  disk is {total:,} sectors = {total * SECTOR:,} bytes\n")
    for kind, cnt in sorted(kinds.items()):
        print(f"    {NAMES.get(kind, hex(kind)):<8} {cnt:>12,} sectors "
              f"({cnt * SECTOR:,} bytes)")
    for name, _ in parts:
        print(f"    entry: {name}")

    if args.list or not args.out:
        return 0

    print()
    written = 0
    with open(args.out, "wb") as out:
        out.truncate(total * SECTOR)
        for _, mish in parts:
            for kind, sec, cnt, coff, clen in chunks(mish):
                if kind == END:
                    continue
                out.seek(sec * SECTOR)
                if kind in (ZERO, IGNORE):
                    out.write(b"\x00" * (cnt * SECTOR))
                else:
                    fh.seek(data_off + coff)
                    out.write(decode(kind, fh.read(clen), cnt * SECTOR))
                written += cnt * SECTOR
                print(f"\r  {written:,} / {total * SECTOR:,} bytes",
                      end="", flush=True)
    print(f"\n\n  wrote {args.out}: {os.path.getsize(args.out):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
