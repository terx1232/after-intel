#!/usr/bin/env python3
"""
xrefs.py -- find every reference to an address in a kernel collection.

Three guesses at where the kernel reads its manifest properties from all failed,
each one placing data somewhere in the device tree. The disassembly had already
said the device tree is not in that path: the object the lookup queries arrives
as an argument, two dereferences deep. Guessing again would be a fourth guess
from the same wrong assumption, so this walks the other way instead - from the
consumer back to whoever calls it.

It finds three kinds of reference, because a function reached only by one kind
looks unreachable if you scan for the others:

    bl  <target>        direct call, 26-bit signed displacement
    b   <target>        tail call or intra-function branch, same encoding
    adrp/add            the address materialised as a value, i.e. taken as a
                        function pointer and stored in a vtable or a table of
                        handlers - which is how most of IOKit dispatches

The scan is linear over the text, so it costs one pass and finds call sites
whose function it cannot name. That is the point: a name is not needed to set a
breakpoint at the caller.

Usage:
    python xrefs.py <kernel> 0xfffffe00084299c0
    python xrefs.py <kernel> 0xfffffe00084299c0 --func   (find the entry first)
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadmap


def sign_extend(value: int, bits: int) -> int:
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def branch_target(word: int, pc: int):
    """Decode B and BL. Returns (target, "b"|"bl") or None."""
    if (word & 0x7C000000) != 0x14000000:
        return None
    imm = sign_extend(word & 0x03FFFFFF, 26) * 4
    return pc + imm, ("bl" if word & 0x80000000 else "b")


def adrp_page(word: int, pc: int):
    """Decode ADRP. Returns (rd, page_base) or None."""
    if (word & 0x9F000000) != 0x90000000:
        return None
    immlo = (word >> 29) & 3
    immhi = (word >> 5) & 0x7FFFF
    imm = sign_extend((immhi << 2) | immlo, 21) << 12
    return word & 0x1F, (pc & ~0xFFF) + imm


def add_imm(word: int):
    """Decode 64-bit ADD immediate. Returns (rd, rn, imm) or None."""
    if (word & 0xFF800000) != 0x91000000:
        return None
    imm = (word >> 10) & 0xFFF
    if (word >> 22) & 1:
        imm <<= 12
    return word & 0x1F, (word >> 5) & 0x1F, imm


def find_entry(data: bytes, base: int, addr: int, limit: int = 0x4000) -> int:
    """Walk back from `addr` to the function's first instruction.

    A function boundary is taken to be a `stp x29, x30, [sp, #-N]!` or a
    `pacibsp`, both of which start essentially every non-leaf arm64e function in
    this kernel. Returns `addr` unchanged if neither is found within `limit`.
    """
    off = addr - base
    for back in range(0, limit, 4):
        i = off - back
        if i < 0:
            break
        (w,) = struct.unpack_from("<I", data, i)
        if w == 0xD503237F:                      # pacibsp
            return base + i
        if (w & 0xFFC07C00) == 0xA9807C00:       # stp x29, x30, [sp, #-N]!
            return base + i
    return addr


def scan(data: bytes, base: int, target: int):
    """Yield (pc, kind, detail) for every reference to `target`."""
    n = len(data) // 4
    adrp_state = {}
    for i in range(n):
        pc = base + i * 4
        (w,) = struct.unpack_from("<I", data, i * 4)

        br = branch_target(w, pc)
        if br and br[0] == target:
            yield pc, br[1], ""
            continue

        a = adrp_page(w, pc)
        if a:
            adrp_state[a[0]] = (a[1], pc)
            continue

        ai = add_imm(w)
        if ai:
            rd, rn, imm = ai
            if rn in adrp_state:
                page, apc = adrp_state[rn]
                if page + imm == target:
                    yield apc, "adrp+add", f"into x{rd}"
            adrp_state.pop(rd, None) if rd != rn else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("target", help="virtual address to find references to")
    ap.add_argument("--func", action="store_true",
                    help="first walk back to the entry of the function "
                         "containing the address, and search for that")
    ap.add_argument("--virt-base", default=None)
    args = ap.parse_args(argv)

    data = open(args.kernel, "rb").read()
    if args.virt_base:
        base = int(args.virt_base, 0)
    else:
        base = loadmap.parse(args.kernel)["vm_low"]

    target = int(args.target, 0)
    if args.func:
        entry = find_entry(data, base, target)
        if entry != target:
            print(f"\n  {target:#x} is {target - entry} bytes into a function "
                  f"entered at {entry:#x}")
        else:
            print(f"\n  no prologue found above {target:#x}; searching for it "
                  f"as given")
        target = entry

    print(f"\n=== references to {target:#x} ===\n")
    found = list(scan(data, base, target))
    if not found:
        print("  none -- reached only indirectly, or not reached at all")
    for pc, kind, detail in found:
        (w,) = struct.unpack_from("<I", data, pc - base)
        print(f"  {pc:#018x}  {w:08x}  {kind:<9} {detail}")
    print(f"\n  {len(found)} reference(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
