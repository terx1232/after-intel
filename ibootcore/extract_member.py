#!/usr/bin/env python3
"""
extract_member.py -- pull one file out of the zip embedded in InstallAssistant.

The macOS installer package is a flat archive with a zip inside it at a fixed
offset, which `gg-zip-members.json` records along with every member name. This
maps that region as a file-like object and hands it to zipfile, so nothing is
copied and a 16 GB archive costs nothing to open.

Written for one file in particular:

    AssetData/boot/Firmware/all_flash/DeviceTree.vma2macosap.im4p

which is Apple's own flattened device tree for the Apple Virtual Machine - the
exact platform this project boots. Everything in devicetree.py before this was
reconstructed from driver strings and matching dictionaries, one property at a
time, with three or four boots per property. This file is the answer sheet.

Usage:
    python extract_member.py --list vma2
    python extract_member.py "AssetData/.../DeviceTree.vma2macosap.im4p" --out dt.im4p
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile

DEFAULT_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "gg-zip-members.json")


class Slice(io.RawIOBase):
    """A read-only window onto part of a file, as a seekable stream."""

    def __init__(self, path, start, length):
        self._f = open(path, "rb")
        self._start = start
        self._len = length
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, off, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self._pos = off
        elif whence == io.SEEK_CUR:
            self._pos += off
        else:
            self._pos = self._len + off
        return self._pos

    def tell(self):
        return self._pos

    def readinto(self, b):
        n = min(len(b), self._len - self._pos)
        if n <= 0:
            return 0
        self._f.seek(self._start + self._pos)
        data = self._f.read(n)
        b[:len(data)] = data
        self._pos += len(data)
        return len(data)

    def close(self):
        self._f.close()
        super().close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("member", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--list", metavar="SUBSTR",
                    help="list member names containing this")
    ap.add_argument("--index", default=DEFAULT_INDEX)
    args = ap.parse_args(argv)

    idx = json.load(open(args.index))
    image, start, length = idx["image"], idx["start"], idx["length"]
    if not os.path.exists(image):
        print(f"error: {image} not found", file=sys.stderr)
        return 2

    # Do not hand the region to zipfile. The recorded `length` runs past the end
    # of the package, so the end-of-central-directory record is not where
    # zipfile looks for it and it reports "File is not a zip file". It does not
    # need to look: the index already carries each member's absolute
    # data_offset, compressed size and method, which is everything required to
    # inflate one member without parsing the archive at all.
    members = {m["name"]: m for m in idx["members"]}
    if args.list is not None:
        for n, m in members.items():
            if args.list.lower() in n.lower():
                print(f"  {m['uncompressed_size']:>12,}  {n}")
        return 0

    if not args.member:
        ap.error("give a member name, or --list")
    m = members.get(args.member)
    if m is None:
        print(f"error: no member named {args.member!r}", file=sys.stderr)
        return 2

    with open(image, "rb") as f:
        f.seek(m["data_offset"])
        raw = f.read(m["compressed_size"])
    if m["method_id"] == 8:
        import zlib
        data = zlib.decompress(raw, -zlib.MAX_WBITS)
    elif m["method_id"] == 0:
        data = raw
    else:
        print(f"error: unsupported method {m['method']}", file=sys.stderr)
        return 2
    if len(data) != m["uncompressed_size"]:
        print(f"error: got {len(data)} bytes, index says "
              f"{m['uncompressed_size']}", file=sys.stderr)
        return 2
    import zlib as _z
    if _z.crc32(data) & 0xFFFFFFFF != m["crc32"]:
        print("error: CRC mismatch", file=sys.stderr)
        return 2
    out = args.out or os.path.basename(args.member)
    open(out, "wb").write(data)
    print(f"\n  {args.member}\n  -> {out}  ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
