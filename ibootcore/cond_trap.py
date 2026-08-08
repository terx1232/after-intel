#!/usr/bin/env python3
"""
cond_trap.py -- freeze on the *failing* call, not the first one.

A plain `b .` planted on a call site stops the CPU the first time it is
reached. When the interesting case is a later iteration, that is useless: the
first pass succeeds and the freeze reports a healthy state.

This diverts the call into a stub that tests the argument first:

    stub:  cbz  x0, stub        ; stop here only when x0 is zero
           bl   <callee>        ; otherwise do the call as before
           b    <after the call>

The call site becomes `b stub`, so x30 is set by the stub's own `bl` and points
back into the stub, which then returns control to the instruction after the
original call. Non-zero arguments are unaffected.

The stub goes in a run of zero padding inside __TEXT_EXEC, which the kernel
maps but does not use.

Usage:
    python cond_trap.py <kernel> --out <patched> --at 0x... --reg 0
"""

from __future__ import annotations

import argparse
import os
import struct
import sys


def encode_cbz(rt: int, pc: int, target: int) -> int:
    delta = target - pc
    if delta % 4:
        raise ValueError("misaligned target")
    imm = delta // 4
    if not (-(1 << 18) <= imm < (1 << 18)):
        raise ValueError("CBZ target out of range")
    return 0xB4000000 | ((imm & 0x7FFFF) << 5) | (rt & 0x1F)


def encode_b(pc: int, target: int, link: bool = False) -> int:
    delta = target - pc
    if delta % 4:
        raise ValueError("misaligned target")
    imm = delta // 4
    if not (-(1 << 25) <= imm < (1 << 25)):
        raise ValueError("branch target out of range")
    return (0x94000000 if link else 0x14000000) | (imm & 0x3FFFFFF)


def bl_target(word: int, pc: int) -> int:
    if (word & 0xFC000000) != 0x94000000:
        raise ValueError(f"{pc:#x} is not a bl: {word:#010x}")
    off = word & 0x3FFFFFF
    if off & 0x2000000:
        off -= 0x4000000
    return pc + off * 4


def find_padding(data: bytes, fileoff: int, size: int, want: int,
                 near: int) -> int | None:
    best, run = None, 0
    for i in range(fileoff, fileoff + size, 4):
        if data[i:i + 4] == b"\x00\x00\x00\x00":
            run += 4
            if run >= want:
                start = i + 4 - run
                d = abs(start - near)
                if best is None or d < best[1]:
                    best = (start, d)
                run = 0
        else:
            run = 0
    return best[0] if best else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out", required=True)
    ap.add_argument("--at", required=True, help="the call site to divert")
    ap.add_argument("--reg", type=int, default=0,
                    help="argument register to test for zero")
    args = ap.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loadmap
    m = loadmap.parse(args.kernel)
    vb = m["vm_low"]
    text = next(s for s in m["segments"] if s["name"] == "__TEXT_EXEC")

    data = bytearray(open(args.kernel, "rb").read())
    site = int(args.at, 0)
    off = site - vb
    (orig,) = struct.unpack_from("<I", data, off)
    callee = bl_target(orig, site)

    pad = find_padding(bytes(data), text["fileoff"], text["filesize"], 16, off)
    if pad is None:
        print("no padding in __TEXT_EXEC", file=sys.stderr)
        return 2
    stub = vb + pad

    words = [
        encode_cbz(args.reg, stub, stub),          # cbz xN, self
        encode_b(stub + 4, callee, link=True),     # bl callee
        encode_b(stub + 8, site + 4),              # b back
    ]
    for i, w in enumerate(words):
        struct.pack_into("<I", data, pad + i * 4, w)
    struct.pack_into("<I", data, off, encode_b(site, stub))

    print(f"\n  call site {site:#x}: bl {callee:#x}")
    print(f"  stub at   {stub:#x} ({stub - site:+#x} away)\n")
    for i, (w, t) in enumerate(zip(words, [
            f"cbz  x{args.reg}, self   <- freezes only on zero",
            f"bl   {callee:#x}",
            f"b    {site + 4:#x}"])):
        print(f"    {stub + i * 4:#018x}  {w:08x}  {t}")

    # Read back rather than trust the writes.
    ok = all(struct.unpack_from("<I", data, pad + i * 4)[0] == w
             for i, w in enumerate(words))
    ok = ok and struct.unpack_from("<I", data, off)[0] == encode_b(site, stub)
    if not ok:
        print("\n  SELF-CHECK FAILED", file=sys.stderr)
        return 1
    print("\n  self-check: stub and diversion read back as written")

    open(args.out, "wb").write(bytes(data))
    print(f"wrote {args.out} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
