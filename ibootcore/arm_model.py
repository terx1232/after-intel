#!/usr/bin/env python3
"""
arm_model.py -- an independent interpreter for the arm64 forms the bench tests.

Written deliberately without looking at a64_to_x64.py, decoding straight from
the Arm ARM field layouts. The point is that expected results come from a
different implementation than the one under test: if both agree on hardware,
they are unlikely to be wrong in the same way. If the translator were also the
oracle, the bench would only prove it is self-consistent.

Covers the integer forms the test set uses: move wide, add and subtract with
immediate and register operands, logical operations both ways, and compare.

Usage:
    python arm_model.py --selftest
    python arm_model.py 8b020020 --x1 5 --x2 7
"""

from __future__ import annotations

import argparse
import sys

MASK64 = (1 << 64) - 1


def _bitmask(n: int, imms: int, immr: int, width: int):
    combined = (n << 6) | (~imms & 0x3F)
    length = combined.bit_length() - 1
    if length < 1:
        return None
    esize = 1 << length
    if esize > width:
        return None
    levels = esize - 1
    s, r = imms & levels, immr & levels
    if s == levels:
        return None
    pattern = (1 << (s + 1)) - 1
    pattern = ((pattern >> r) | (pattern << (esize - r))) & ((1 << esize) - 1)
    value = 0
    for i in range(width // esize):
        value |= pattern << (i * esize)
    return value & ((1 << width) - 1)


class Unmodelled(Exception):
    pass


def step(word: int, regs: dict) -> dict:
    """Apply one instruction to a register dict {0..30: value}. Returns a copy."""
    r = dict(regs)

    def get(n):
        return 0 if n == 31 else r.get(n, 0)

    def put(n, v):
        if n != 31:
            r[n] = v & MASK64

    sf = (word >> 31) & 1
    width = 64 if sf else 32
    wmask = MASK64 if sf else 0xFFFFFFFF

    # move wide: MOVZ / MOVK / MOVN
    if (word & 0x7F800000) == 0x52800000:                 # MOVZ
        rd, imm, hw = word & 0x1F, (word >> 5) & 0xFFFF, (word >> 21) & 3
        put(rd, (imm << (16 * hw)) & wmask)
        return r
    if (word & 0x7F800000) == 0x72800000:                 # MOVK
        rd, imm, hw = word & 0x1F, (word >> 5) & 0xFFFF, (word >> 21) & 3
        keep = get(rd) & ~(0xFFFF << (16 * hw))
        put(rd, (keep | (imm << (16 * hw))) & wmask)
        return r
    if (word & 0x7F800000) == 0x12800000:                 # MOVN
        rd, imm, hw = word & 0x1F, (word >> 5) & 0xFFFF, (word >> 21) & 3
        put(rd, (~(imm << (16 * hw))) & wmask)
        return r

    # add/sub immediate
    if (word & 0x7F800000) in (0x11000000, 0x51000000, 0x31000000, 0x71000000):
        sub = (word & 0x40000000) != 0
        rd, rn = word & 0x1F, (word >> 5) & 0x1F
        imm = (word >> 10) & 0xFFF
        if (word >> 22) & 1:
            imm <<= 12
        val = (get(rn) - imm) if sub else (get(rn) + imm)
        if (word & 0x20000000) and rd == 31:              # ADDS/SUBS to XZR
            return r
        put(rd, val & wmask)
        return r

    # logical immediate
    if (word & 0x1F800000) == 0x12000000:
        opc = (word >> 29) & 3
        n = (word >> 22) & 1
        imm = _bitmask(n, (word >> 10) & 0x3F, (word >> 16) & 0x3F, width)
        if imm is None:
            raise Unmodelled("unallocated logical immediate")
        rd, rn = word & 0x1F, (word >> 5) & 0x1F
        a = get(rn)
        val = (a & imm, a | imm, a ^ imm, a & imm)[opc]
        if opc == 3 and rd == 31:
            return r
        put(rd, val & wmask)
        return r

    # add/sub shifted register
    if (word & 0x1F000000) == 0x0B000000:
        opc = (word >> 29) & 3
        shift, imm6 = (word >> 22) & 3, (word >> 10) & 0x3F
        rd, rn, rm = word & 0x1F, (word >> 5) & 0x1F, (word >> 16) & 0x1F
        b = get(rm)
        if imm6:
            b = {0: lambda v: v << imm6,
                 1: lambda v: (v & MASK64) >> imm6,
                 2: lambda v: v >> imm6,
                 3: lambda v: ((v >> imm6) | (v << (width - imm6)))}[shift](b)
        val = (get(rn) - b) if (opc & 2) else (get(rn) + b)
        if (opc & 1) and rd == 31:
            return r
        put(rd, val & wmask)
        return r

    # logical shifted register (MOV is ORR with XZR)
    if (word & 0x1F000000) == 0x0A000000:
        opc = (word >> 29) & 3
        shift, imm6 = (word >> 22) & 3, (word >> 10) & 0x3F
        rd, rn, rm = word & 0x1F, (word >> 5) & 0x1F, (word >> 16) & 0x1F
        b = get(rm)
        if imm6:
            b = {0: lambda v: v << imm6,
                 1: lambda v: (v & MASK64) >> imm6,
                 2: lambda v: v >> imm6,
                 3: lambda v: ((v >> imm6) | (v << (width - imm6)))}[shift](b)
        a = get(rn)
        val = (a & b, a | b, a ^ b, a & b)[opc]
        if opc == 3 and rd == 31:
            return r
        put(rd, val & wmask)
        return r

    raise Unmodelled(f"{word:08x} not modelled")


def selftest() -> int:
    cases = [
        (0xD2800141, {}, 1, 10, "movz x1, #10"),
        (0xD2801002, {}, 2, 128, "movz x2, #128"),
        (0x8B020020, {1: 5, 2: 7}, 0, 12, "add x0, x1, x2"),
        (0xCB020020, {1: 20, 2: 7}, 0, 13, "sub x0, x1, x2"),
        (0xAA0203E3, {2: 0x99}, 3, 0x99, "mov x3, x2"),
        (0x91000421, {1: 41}, 1, 42, "add x1, x1, #1"),
        (0xD1000421, {1: 43}, 1, 42, "sub x1, x1, #1"),
        (0x8A020020, {1: 0xF0, 2: 0x3C}, 0, 0x30, "and x0, x1, x2"),
        (0xAA020020, {1: 0xF0, 2: 0x0C}, 0, 0xFC, "orr x0, x1, x2"),
        (0xCA020020, {1: 0xFF, 2: 0x0F}, 0, 0xF0, "eor x0, x1, x2"),
    ]
    ok = True
    print("independent model, checked against hand-computed results:\n")
    for word, setup, reg, expect, desc in cases:
        got = step(word, setup).get(reg, 0)
        good = got == expect
        ok &= good
        print(f"  {word:08x}  {desc:<18} x{reg} = {got:#x}"
              f"{'' if good else f'   MISMATCH, expected {expect:#x}'}")
    print("\n  " + ("PASS" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("word", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    for i in range(4):
        ap.add_argument(f"--x{i}", default="0")
    args = ap.parse_args(argv)

    if args.selftest or not args.word:
        return selftest()

    regs = {i: int(getattr(args, f"x{i}"), 0) for i in range(4)}
    out = step(int(args.word, 16), regs)
    for i in range(4):
        print(f"  x{i} = {out.get(i, 0):#018x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
