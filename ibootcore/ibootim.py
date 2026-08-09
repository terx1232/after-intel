#!/usr/bin/env python3
"""
ibootim.py -- decode Apple's iBootIm boot logo format.

The Apple logo shown while a Mac boots is drawn by iBoot, not by the kernel, and
this project replaces iBoot with a stub. Drawing it therefore falls to the stub -
but the artwork does not have to be invented. It ships in the installer the user
already has:

    AssetData/boot/Firmware/all_flash/applelogo@1x~mac-USBc.im4p
    AssetData/boot/Firmware/all_flash/applelogo@2x~mac-USBc.im4p

Inside the IM4P wrapper (payload type `logo`, built by EmbeddedImages-184) is a
container Apple calls iBootIm:

    00  "iBootIm\0"
    08  four bytes, version or checksum
    0c  compression, stored reversed: "sszl" is lzss
    10  format, stored reversed: "yerg" is grey
    14  uint16 width
    16  uint16 height
    18  ...
    40  payload

The greyscale form is one byte of coverage per pixel - an alpha mask, not a
colour image - which is why the logo is always painted in a single colour.

The compression is the same LZSS Apple uses for kernelcaches: 4096-byte ring
buffer, 18-byte maximum match, threshold 2, buffer prefilled with zeros rather
than spaces.

Usage:
    python ibootim.py applelogo2x.bin --out logo.pgm
"""

from __future__ import annotations

import argparse
import struct
import sys

MAGIC = b"iBootIm\x00"
HEADER = 0x40

N = 4096          # ring buffer size
F = 18            # longest match
THRESHOLD = 2


def lzss_decompress(src: bytes, expected: int | None = None) -> bytes:
    """Apple's LZSS, as used for kernelcaches and boot images."""
    out = bytearray()
    # Prefilled with spaces, not zeros. XNU's decompress_lzss does
    #     for (i = 0; i < N - F; i++) text_buf[i] = ' ';
    # and getting this wrong does not fail loudly - it decodes to a plausible
    # amount of plausible-looking bytes that are simply not the image.
    ring = bytearray(b" " * N)
    r = N - F
    i = 0
    flags = 0
    while i < len(src):
        flags >>= 1
        if not (flags & 0x100):
            if i >= len(src):
                break
            flags = src[i] | 0xFF00
            i += 1
        if flags & 1:
            if i >= len(src):
                break
            c = src[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) % N
        else:
            if i + 1 >= len(src):
                break
            a, b = src[i], src[i + 1]
            i += 2
            pos = a | ((b & 0xF0) << 4)
            length = (b & 0x0F) + THRESHOLD
            for k in range(length + 1):
                c = ring[(pos + k) % N]
                out.append(c)
                ring[r] = c
                r = (r + 1) % N
        if expected is not None and len(out) >= expected:
            break
    return bytes(out)


def decode(blob: bytes):
    """Return (width, height, greyscale bytes)."""
    if blob[:8] != MAGIC:
        raise ValueError("not an iBootIm")
    comp = blob[0x0C:0x10][::-1].decode("ascii", "replace")
    fmt = blob[0x10:0x14][::-1].decode("ascii", "replace")
    w, h = struct.unpack_from("<HH", blob, 0x14)
    if fmt != "grey":
        raise ValueError(f"unsupported format {fmt!r}")
    body = blob[HEADER:]
    if comp == "lzss":
        pix = lzss_decompress(body, w * h)
    elif comp in ("none", "\x00\x00\x00\x00"):
        pix = body
    else:
        raise ValueError(f"unsupported compression {comp!r}")
    if len(pix) < w * h:
        pix = pix + b"\x00" * (w * h - len(pix))
    return w, h, pix[:w * h]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out", help="write a binary PGM of the mask")
    args = ap.parse_args(argv)

    blob = open(args.image, "rb").read()
    w, h, pix = decode(blob)
    nz = sum(1 for b in pix if b)
    print(f"\n  {w} x {h}, {len(pix):,} bytes of coverage")
    print(f"  {nz:,} non-zero pixels ({100 * nz / len(pix):.1f}%)")

    if args.out:
        with open(args.out, "wb") as f:
            f.write(b"P5\n%d %d\n255\n" % (w, h))
            f.write(pix)
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
