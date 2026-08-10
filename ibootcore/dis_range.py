#!/usr/bin/env python3
"""
dis_range.py -- disassemble a virtual address range out of a kernel collection,
and find where a given instruction word occurs in __TEXT_EXEC.

Everything in this stage that went wrong went wrong because a listing was read
and then assumed to describe what ran. This tool is for the first half of that
only: locating candidates. Whether an instruction executes is settled by
freezing it, never by reading it here.

Addresses may be given in full (0xfffffe000a0098e0) or in the short form used
throughout the log (0xa0098e0); anything below 4 GiB is taken as an offset from
0xfffffe0000000000.

Usage:
    python dis_range.py <kernel> --at 0xa0098e0 --count 40
    python dis_range.py <kernel> --at 0xa0098e0 --to 0xa009a40
    python dis_range.py <kernel> --find 0xd2dfc200 --mask 0xffffffe0
    python dis_range.py <kernel> --find-const 0xfffffe1000000000
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

KV_HIGH = 0xFFFFFE0000000000


def full_va(v: int) -> int:
    return v if v > 0xFFFFFFFF else (KV_HIGH | v)


def short(va: int) -> str:
    return f"0x{va - KV_HIGH:x}" if va >= KV_HIGH else f"{va:#x}"


def movz_movk_words(value: int, rd_any: bool = True):
    """The MOVZ/MOVK words a compiler emits for a 64-bit immediate.

    Returned with the Rd field cleared, to be matched under a 0xffffffe0 mask.
    """
    out = []
    for hw in range(4):
        chunk = (value >> (16 * hw)) & 0xFFFF
        if chunk == 0:
            continue
        movz = 0xD2800000 | (hw << 21) | (chunk << 5)
        movk = 0xF2800000 | (hw << 21) | (chunk << 5)
        out.append((hw, chunk, movz, movk))
    return out


def load(kernel: str):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loadmap
    m = loadmap.parse(kernel)
    data = open(kernel, "rb").read()
    return m, data


def text_exec(m: dict):
    return next(s for s in m["segments"] if s["name"] == "__TEXT_EXEC")


def disassemble(data: bytes, vb: int, start: int, end: int) -> None:
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    off = start - vb
    n = end - start
    for ins in md.disasm(data[off:off + n], start):
        (word,) = struct.unpack_from("<I", data, ins.address - vb)
        print(f"  {short(ins.address):>12}  {word:08x}  {ins.mnemonic:<8} {ins.op_str}")


def find_word(data: bytes, m: dict, want: int, mask: int) -> list[int]:
    seg = text_exec(m)
    vb = int(args.virt_base, 0) if getattr(args, "virt_base", None) else m["vm_low"]
    hits = []
    lo, hi = seg["fileoff"], seg["fileoff"] + seg["filesize"]
    for off in range(lo, hi, 4):
        (w,) = struct.unpack_from("<I", data, off)
        if (w & mask) == (want & mask):
            hits.append(vb + off)
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--at")
    ap.add_argument("--to")
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--find", help="instruction word to search for in __TEXT_EXEC")
    ap.add_argument("--mask", default="0xffffffff")
    ap.add_argument("--find-const", help="64-bit immediate; finds its MOVZ")
    ap.add_argument("--virt-base",
                    help="use this as the load base instead of the kernel load "
                         "map, so a plain userland Mach-O can be read")
    ap.add_argument("--context", type=int, default=0,
                    help="instructions to disassemble around each hit")
    args = ap.parse_args(argv)

    m, data = load(args.kernel)
    vb = int(args.virt_base, 0) if getattr(args, "virt_base", None) else m["vm_low"]

    if args.find_const:
        value = int(args.find_const, 0)
        parts = movz_movk_words(value)
        hw, chunk, movz, _ = parts[0]
        print(f"\n  {value:#018x} materialises as")
        for hw_, chunk_, movz_, movk_ in parts:
            print(f"    movz/movk #{chunk_:#06x}, lsl #{hw_ * 16:<2}  "
                  f"-> {movz_:08x} / {movk_:08x}")
        print(f"\n  scanning __TEXT_EXEC for the first MOVZ ({movz:08x}, Rd masked out)")
        hits = find_word(data, m, movz, 0xFFFFFFE0)
        print(f"  {len(hits)} hit(s)\n")
        for h in hits:
            (w,) = struct.unpack_from("<I", data, h - vb)
            print(f"    {short(h):>12}  {w:08x}  rd = x{w & 0x1F}")
            if args.context:
                disassemble(data, vb, h - 4 * args.context,
                            h + 4 * (args.context + 1))
                print()
        return 0

    if args.find:
        want = int(args.find, 0)
        mask = int(args.mask, 0)
        hits = find_word(data, m, want, mask)
        print(f"\n  {len(hits)} hit(s) for {want:08x} & {mask:08x}\n")
        for h in hits:
            (w,) = struct.unpack_from("<I", data, h - vb)
            print(f"    {short(h):>12}  {w:08x}")
            if args.context:
                disassemble(data, vb, h - 4 * args.context,
                            h + 4 * (args.context + 1))
                print()
        return 0

    if not args.at:
        ap.error("--at is required unless --find/--find-const is used")
    start = full_va(int(args.at, 0))
    end = full_va(int(args.to, 0)) if args.to else start + 4 * args.count
    print(f"\n  {short(start)} .. {short(end)}   (file offset "
          f"{start - vb:#x})\n")
    disassemble(data, vb, start, end)
    return 0


if __name__ == "__main__":
    sys.exit(main())

