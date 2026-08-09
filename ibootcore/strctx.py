#!/usr/bin/env python3
"""
strctx.py -- print the strings surrounding a string in a kernel collection.

This is the tool that broke the `crypto-hash-method` deadlock, done by hand
three times before being written down. A compiler puts a function's string
literals next to each other in the order the function uses them, so the
neighbours of a string say what the code around it does - and, when one of the
neighbours is a device tree path, they say where the code reads from.

That is how the secure-boot panic was solved after three wrong guesses. The name
occurred twice; the second copy sat four bytes after "/chosen" and immediately
before its own two legal values:

    fffffe000732f934  /chosen
    fffffe000732f93c  crypto-hash-method
    fffffe000732f94f  sha2-384
    fffffe000732f958  sha1

Nothing else had to be disassembled. Guessing at the device tree cost three
attempts; reading the literal pool cost one.

Usage:
    python strctx.py <kernel> "crypto-hash-method" [--before 8] [--after 16]
    python strctx.py <kernel> --at 0xfffffe000732f900 --after 40
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadmap

MIN_RUN = 4


def strings_in(buf: bytes, base_off: int, base_va: int):
    """Yield (va, text) for every printable NUL-terminated run."""
    out, start = [], None
    for i, c in enumerate(buf):
        if 32 <= c < 127:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= MIN_RUN:
                out.append((base_va + base_off + start,
                            buf[start:i].decode("ascii")))
            start = None
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("needle", nargs="?")
    ap.add_argument("--at", help="dump around this virtual address instead")
    ap.add_argument("--before", type=int, default=6, help="strings before")
    ap.add_argument("--after", type=int, default=18, help="strings after")
    ap.add_argument("--window", type=lambda s: int(s, 0), default=0x600,
                    help="bytes to scan either side")
    ap.add_argument("--virt-base", default=None)
    args = ap.parse_args(argv)

    data = open(args.kernel, "rb").read()
    base = (int(args.virt_base, 0) if args.virt_base
            else loadmap.parse(args.kernel)["vm_low"])

    if args.at:
        hits = [int(args.at, 0) - base]
    else:
        if not args.needle:
            ap.error("give a string to find, or --at")
        needle = args.needle.encode()
        hits, i = [], data.find(needle)
        while i >= 0:
            hits.append(i)
            i = data.find(needle, i + 1)
        if not hits:
            print(f"  {args.needle!r} does not occur")
            return 1
        print(f"\n  {args.needle!r}: {len(hits)} occurrence(s)")

    for h in hits:
        lo = max(0, h - args.window)
        hi = min(len(data), h + args.window)
        found = strings_in(data[lo:hi], lo, base)
        # Locate the hit among them and window by string count, not by bytes,
        # so a dense literal pool and a sparse one both come out readable.
        idx = 0
        for k, (va, _t) in enumerate(found):
            if va <= base + h:
                idx = k
        lo_i = max(0, idx - args.before)
        hi_i = min(len(found), idx + args.after + 1)
        print(f"\n=== around {base + h:#018x} (file {h:#x}) ===\n")
        for k in range(lo_i, hi_i):
            va, text = found[k]
            mark = "->" if k == idx else "  "
            print(f"  {mark} {va:#018x}  {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
