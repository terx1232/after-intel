#!/usr/bin/env python3
"""
bootscreen.py -- build the picture iBoot would have left in the framebuffer.

On a real Mac the Apple logo is not drawn by macOS. iBoot programs the display,
loads `applelogo@Nx~mac.im4p` out of its own firmware volume, decodes it and
blits it; the kernel then draws its progress bar on top of a picture that is
already there, and contains no logo of its own. So putting the logo on screen
here is not an imitation of a Mac - it is the same operation, in the same place
in the boot chain, from the same file. The only difference is that the stub doing
it is a few hundred bytes rather than a megabyte.

The artwork is Apple's, taken from the installer the user already has, decoded by
ibootim.py. Nothing is redistributed: the file is read locally and the rendered
framebuffer is written next to the build.

The logo is a coverage mask, not a colour image, which is why a Mac can tint it -
white on a dark boot, dark on a light one. This composites it in a single colour
over a background, both configurable.

Usage:
    python bootscreen.py --logo applelogo2x.bin --out screen.bin
    python bootscreen.py --logo applelogo2x.bin --out screen.bin --geometry 1024x768
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ibootim


def render(logo_blob: bytes, width: int, height: int,
           fg: int = 0xFFFFFF, bg: int = 0x000000,
           centre_bias: float = 0.5) -> bytes:
    """A width x height XRGB8888 framebuffer with the logo composited on it."""
    lw, lh, pix = ibootim.decode(logo_blob)

    # The mask is stored inverted: 0 inside the shape, 0xff outside. Profiling
    # the channel is what settled that - the apple, its leaf and the bite all
    # appear as the low-valued region.
    cov = bytes(255 - v for v in pix)

    fb = bytearray(struct.pack("<I", bg) * (width * height))
    x0 = (width - lw) // 2
    y0 = int(height * centre_bias) - lh // 2

    fr, fg_, fb_ = (fg >> 16) & 0xFF, (fg >> 8) & 0xFF, fg & 0xFF
    br, bg_, bb_ = (bg >> 16) & 0xFF, (bg >> 8) & 0xFF, bg & 0xFF

    for y in range(lh):
        dy = y0 + y
        if not (0 <= dy < height):
            continue
        row = cov[y * lw:(y + 1) * lw]
        base = (dy * width + x0) * 4
        for x, a in enumerate(row):
            dx = x0 + x
            if not (0 <= dx < width) or a == 0:
                continue
            r = (fr * a + br * (255 - a)) // 255
            g = (fg_ * a + bg_ * (255 - a)) // 255
            b = (fb_ * a + bb_ * (255 - a)) // 255
            struct.pack_into("<I", fb, base + x * 4, (r << 16) | (g << 8) | b)
    return bytes(fb)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logo", required=True, help="decoded iBootIm payload")
    ap.add_argument("--out", required=True)
    ap.add_argument("--geometry", default="1024x768")
    ap.add_argument("--fg", default="0xffffff")
    ap.add_argument("--bg", default="0x000000")
    ap.add_argument("--bias", type=float, default=0.42,
                    help="vertical centre as a fraction of the height; a Mac "
                         "sits the logo a little above centre")
    ap.add_argument("--png", help="also write a PNG, to look at it")
    args = ap.parse_args(argv)

    w, _, h = args.geometry.lower().partition("x")
    w, h = int(w), int(h)
    blob = open(args.logo, "rb").read()
    fb = render(blob, w, h, int(args.fg, 0), int(args.bg, 0), args.bias)
    open(args.out, "wb").write(fb)

    lw, lh, _ = ibootim.decode(blob)
    print(f"\n  logo    {lw} x {lh}")
    print(f"  screen  {w} x {h} XRGB8888, {len(fb):,} bytes")
    print(f"  wrote {args.out}")

    if args.png:
        import ppm2png
        rgb = bytearray()
        for i in range(0, len(fb), 4):
            rgb += bytes((fb[i + 2], fb[i + 1], fb[i]))
        ppm2png.write_png(args.png, w, h, bytes(rgb))
        print(f"  wrote {args.png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
