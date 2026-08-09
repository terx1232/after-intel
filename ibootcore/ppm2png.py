#!/usr/bin/env python3
"""
ppm2png.py -- convert QEMU's screendump output to PNG.

QEMU's monitor writes screenshots as binary PPM, which nothing on Windows opens.
PNG needs only zlib and a CRC, both in the standard library, so this avoids
adding an image dependency to a project that has none.

Usage:
    python ppm2png.py screen.ppm --out screen.png [--scale 1]
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib


def read_ppm(path: str):
    with open(path, "rb") as f:
        if f.readline().strip() != b"P6":
            raise ValueError("not a binary PPM")
        # Dimensions and maxval, skipping comments.
        fields = []
        while len(fields) < 3:
            line = f.readline()
            if line.startswith(b"#"):
                continue
            fields += line.split()
        w, h, _maxv = (int(x) for x in fields[:3])
        return w, h, f.read(w * h * 3)


def chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, w: int, h: int, rgb: bytes) -> int:
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)                       # filter type 0, none
        raw += rgb[y * stride:(y + 1) * stride]
    body = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
    open(path, "wb").write(body)
    return len(body)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ppm")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    w, h, rgb = read_ppm(args.ppm)
    n = write_png(args.out, w, h, rgb)
    print(f"\n  {args.ppm}: {w}x{h}")
    print(f"  wrote {args.out} ({n:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
