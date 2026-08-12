#!/usr/bin/env python3
"""
constscan.py -- recover short inline string constants from arm64 code.

A label of eight bytes or fewer is not a string as far as the compiler is
concerned. It is a 64-bit immediate, built with a MOVZ and up to three MOVKs and
spilled to the stack, so it never reaches __cstring and no string search will
find it. That is exactly what happened with the AEA key derivation labels: only
the diagnostic text "derivating RHEK" is in the binary, while the label the KDF
actually consumes is invisible to `strings`.

This scans for those immediates and decodes them back into text. It does not
take a list of guesses: it walks every MOVZ/MOVK cluster, reassembles the
constant, and reports the ones whose bytes read as ASCII. The labels come out of
the binary rather than out of a hypothesis.

Usage:
    python constscan.py libAppleArchive.dylib
    python constscan.py libAppleArchive.dylib --near 0x2bae4 --window 0x400
    python constscan.py libAppleArchive.dylib --want AEA_AMK
"""

from __future__ import annotations

import argparse
import os
import string
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import machobase

PRINTABLE = set((string.ascii_letters + string.digits + "_-. /:@").encode())


def decode_movz(w: int):
    """(rd, shift, imm16) for MOVZ Xd, #imm, lsl #shift."""
    if (w & 0xFF800000) != 0xD2800000:
        return None
    return w & 0x1F, ((w >> 21) & 3) * 16, (w >> 5) & 0xFFFF


def decode_movk(w: int):
    """(rd, shift, imm16) for MOVK Xd, #imm, lsl #shift."""
    if (w & 0xFF800000) != 0xF2800000:
        return None
    return w & 0x1F, ((w >> 21) & 3) * 16, (w >> 5) & 0xFFFF


def constants(data: bytes, base: int, lo: int, hi: int, window: int = 8):
    """Yield (address, value) for each MOVZ-rooted immediate in [lo, hi)."""
    for off in range(lo, hi - 4, 4):
        (w,) = struct.unpack_from("<I", data, off)
        z = decode_movz(w)
        if not z:
            continue
        rd, shift, imm = z
        value = imm << shift
        # Collect the MOVKs that finish this register before anything else
        # writes it. Compilers interleave, so look a little way ahead.
        for k in range(1, window + 1):
            j = off + 4 * k
            if j + 4 > hi:
                break
            (w2,) = struct.unpack_from("<I", data, j)
            m = decode_movk(w2)
            if m and m[0] == rd:
                value |= m[2] << m[1]
            elif decode_movz(w2) and decode_movz(w2)[0] == rd:
                break
        yield base + off, value


def as_text(value: int):
    """The constant read as bytes, if it is plausibly a label."""
    raw = value.to_bytes(8, "little")
    trimmed = raw.rstrip(b"\x00")
    if len(trimmed) < 3:
        return None
    if any(c not in PRINTABLE for c in trimmed):
        return None
    # A label starts with a letter; lengths and offsets often decode as text by
    # accident but rarely satisfy that as well.
    if trimmed[0:1].isalpha() is False:
        return None
    return trimmed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("--near", help="restrict to a window around this address")
    ap.add_argument("--window", default="0x400")
    ap.add_argument("--want", action="append", default=[],
                    help="report where this exact text is materialised")
    args = ap.parse_args(argv)

    data = open(args.binary, "rb").read()
    base = machobase.text_base(data)

    lo, hi = 0, len(data)
    if args.near:
        centre = int(args.near, 0) - base if int(args.near, 0) > base else int(args.near, 0)
        w = int(args.window, 0)
        lo, hi = max(0, centre - w), min(len(data), centre + w)

    if args.want:
        wanted = {}
        for s in args.want:
            raw = s.encode()[:8].ljust(8, b"\x00")
            wanted[int.from_bytes(raw, "little")] = s
        print()
        found = {}
        for addr, value in constants(data, base, lo, hi):
            if value in wanted:
                found.setdefault(wanted[value], []).append(addr)
        for s in args.want:
            where = found.get(s, [])
            if where:
                print(f"  {s!r}: {', '.join(hex(a) for a in where)}")
            else:
                print(f"  {s!r}: not materialised")
        return 0

    seen = {}
    for addr, value in constants(data, base, lo, hi):
        t = as_text(value)
        if t:
            seen.setdefault(t, []).append(addr)

    print(f"\n  {len(seen)} inline text constants in "
          f"{base + lo:#x}..{base + hi:#x}\n")
    for t, where in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        head = ", ".join(hex(a) for a in where[:4])
        more = f" (+{len(where) - 4})" if len(where) > 4 else ""
        print(f"    {t.decode():<12} {len(where):>3}x  {head}{more}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
