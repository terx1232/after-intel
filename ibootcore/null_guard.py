#!/usr/bin/env python3
"""
null_guard.py -- make a heavily-called helper return early on a null argument.

Chasing the data abort at 0xfffffe0009e41eb0 by patching the faulting load only
moved it a few instructions on. Looking at what the function actually is
explains why: it has 549 callers, takes a pointer in x0, aligns it to sixteen
bytes and loads 128 bits with `ldr q0`. That is a bulk memory routine, not
anything paravirtual. The null is an argument somebody passed it, and the cause
is upstream.

Which suggests a different move: rather than stopping the fault, make the
routine tolerate the argument. Its prologue is

    pacibsp                     <- a no-op under a PAC-as-identity model
    stp x29, x30, [sp, #-16]!
    mov x29, sp

so replacing the first instruction with `cbz x0, <stub>` returns before the
frame is pushed, with x30 still holding the caller's return address. A plain
`ret` in the stub is then correct. Non-null arguments fall straight through and
behave exactly as before.

The stub goes in a run of zero padding inside the executable segment, which the
kernel maps but does not use.

This is a bring-up measure. A routine that silently does nothing on null is not
correct behaviour; it is a way to find out what the code after it does.

Usage:
    python null_guard.py <kernel> --out <patched> [--func 0x...]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

RET = 0xD65F03C0


def encode_cbz(rt: int, pc: int, target: int) -> int:
    """CBZ Xt, <label> -- 64-bit form."""
    delta = target - pc
    if delta % 4:
        raise ValueError("misaligned branch target")
    imm = delta // 4
    if not (-(1 << 18) <= imm < (1 << 18)):
        raise ValueError(f"target {target:#x} out of CBZ range from {pc:#x}")
    return 0xB4000000 | ((imm & 0x7FFFF) << 5) | (rt & 0x1F)


def encode_b(pc: int, target: int) -> int:
    """B <label> -- unconditional, +/-128 MiB."""
    delta = target - pc
    if delta % 4:
        raise ValueError("misaligned branch target")
    imm = delta // 4
    if not (-(1 << 25) <= imm < (1 << 25)):
        raise ValueError(f"target {target:#x} out of B range from {pc:#x}")
    return 0x14000000 | (imm & 0x3FFFFFF)


def find_padding(data: bytes, fileoff: int, size: int, want: int,
                 near: int) -> int:
    """A run of `want` zero bytes inside the segment, closest to `near`."""
    best = None
    run = 0
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
    ap.add_argument("--func", default="0xfffffe0009e41ea0",
                    help="entry point of the routine to guard")
    ap.add_argument("--reg", type=int, default=0,
                    help="which argument register to test for null")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loadmap
    m = loadmap.parse(args.kernel)
    vb = m["vm_low"]
    func = int(args.func, 0)

    data = bytearray(open(args.kernel, "rb").read())
    text = next(s for s in m["segments"] if s["name"] == "__TEXT_EXEC")

    # The prologue must not be touched. Removing `pacibsp` breaks its pairing
    # with the `retab` in the epilogue, and QEMU implements pointer
    # authentication, so the return then fails with ESR 0x1c. The first
    # attempt did exactly that.
    #
    # Divert the instruction that computes the address instead, into a stub
    # that either does the original work or unwinds the frame the prologue
    # already pushed and returns properly.
    site = func + 0xC                      # `and x1, x0, #mask`
    off = site - vb
    (orig,) = struct.unpack_from("<I", data, off)
    print(f"\n=== null guard on {func:#x}, testing x{args.reg} ===\n")
    print(f"  diverting {site:#x}: {orig:#010x}")

    pad = find_padding(bytes(data), text["fileoff"], text["filesize"], 24, off)
    if pad is None:
        print("  no padding found in __TEXT_EXEC", file=sys.stderr)
        return 2
    stub_va = vb + pad
    print(f"  stub at          : {stub_va:#x} ({stub_va - site:+#x} away)")

    LDP_X29_X30_SP_16 = 0xA8C17BFD         # ldp x29, x30, [sp], #16
    RETAB = 0xD65F0FFF

    stub = [
        encode_cbz(args.reg, stub_va, stub_va + 12),  # cbz xN, early_return
        orig,                                   # the work we displaced
        encode_b(stub_va + 8, site + 4),        # back to the instruction after
        LDP_X29_X30_SP_16,                      # early_return: undo the frame
        RETAB,                                  # authenticated return
    ]
    for i, w in enumerate(stub):
        struct.pack_into("<I", data, pad + i * 4, w)

    br = encode_b(site, stub_va)
    struct.pack_into("<I", data, off, br)
    print(f"  {orig:#010x} -> {br:#010x}   b {stub_va:#x}")
    print("\n  stub:")
    for i, (w, txt) in enumerate(zip(stub, [
            f"cbz  x{args.reg}, +12", "the displaced instruction",
            "b    back", "ldp  x29, x30, [sp], #16", "retab"])):
        print(f"    {stub_va + i * 4:#018x}  {w:08x}  {txt}")

    open(args.out, "wb").write(bytes(data))
    print(f"\nwrote {args.out} ({len(data):,} bytes)")
    print("\nA routine that quietly does nothing on null is not correct; this is")
    print("a way to see what the code after it does.")

    if args.json:
        json.dump({"func": func, "reg": args.reg, "site": site,
                   "stub": stub_va, "displaced": orig, "branch": br},
                  open(args.json, "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
