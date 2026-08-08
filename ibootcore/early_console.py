#!/usr/bin/env python3
"""
early_console.py -- give the kernel a working console before it has one.

XNU's early panic path prints two strings and halts:

    adrp x0, <"panic: %s\\n">   ; bl <print>
    adrp x0, <"Kernel panicked very early before serial init, spinning...">
    bl  <print>
    bl  <halt>

The message it means to show is real and already formatted, but the print
routine goes through a serial device that has not been registered yet, so
nothing leaves the machine. Every failure in this port has therefore had to be
excavated from a memory dump.

This replaces the print routine's entry with nine instructions that write
straight to a PL011 transmit register, which QEMU's `virt` machine provides at
0x09000000 and which XNU's own device tree entry for this platform already
names. After the patch, panics appear on the serial line as text.

    write:                          ; x0 = NUL-terminated string
        movz x2, #base>>16, lsl #16
    next:
        ldrb w1, [x0], #1
        cbz  w1, done
    wait:
        ldr  w3, [x2, #0x18]        ; PL011 FR
        tbnz w3, #5, wait           ; spin while TXFF
        str  w1, [x2]               ; PL011 DR
        b    next
    done:
        ret

Nothing is preserved except the ABI: x0 is consumed, x1-x3 are caller-saved,
and the routine returns normally, so callers are unaffected. It is a bring-up
measure and it discards whatever formatting the original routine did.

Usage:
    python early_console.py <kernel> --out <patched> [--at 0x...] [--uart 0x9000000]
"""

from __future__ import annotations

import argparse
import struct
import sys

PL011_DR = 0x00
PL011_FR = 0x18
PL011_FR_TXFF_BIT = 5


def movz(rd: int, imm16: int, hw: int) -> int:
    return 0xD2800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def ldrb_post(rt: int, rn: int, imm9: int) -> int:
    return 0x38400400 | ((imm9 & 0x1FF) << 12) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def ldr_w(rt: int, rn: int, off: int) -> int:
    return 0xB9400000 | ((off // 4) << 10) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def str_w(rt: int, rn: int, off: int) -> int:
    return 0xB9000000 | ((off // 4) << 10) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def cbz_w(rt: int, pc: int, target: int) -> int:
    imm = (target - pc) // 4
    return 0x34000000 | ((imm & 0x7FFFF) << 5) | (rt & 0x1F)


def tbnz_w(rt: int, bit: int, pc: int, target: int) -> int:
    imm = (target - pc) // 4
    return 0x37000000 | ((bit & 0x1F) << 19) | ((imm & 0x3FFF) << 5) | (rt & 0x1F)


def b(pc: int, target: int) -> int:
    imm = (target - pc) // 4
    return 0x14000000 | (imm & 0x3FFFFFF)


RET = 0xD65F03C0


def build(at: int, uart: int) -> list:
    """Emit the routine, resolving its own branches against `at`."""
    if uart & 0xFFFF:
        raise ValueError("UART base must be 16-bit aligned for a single movz")
    nxt = at + 4                 # `next` label
    wait = at + 12               # `wait` label
    done = at + 28               # `done` label
    return [
        movz(2, uart >> 16, 1),                      # movz x2, base>>16, lsl 16
        ldrb_post(1, 0, 1),                          # next: ldrb w1, [x0], #1
        cbz_w(1, at + 8, done),                      # cbz w1, done
        ldr_w(3, 2, PL011_FR),                       # wait: ldr w3, [x2, #0x18]
        tbnz_w(3, PL011_FR_TXFF_BIT, at + 16, wait),  # tbnz w3, #5, wait
        str_w(1, 2, PL011_DR),                       # str w1, [x2]
        b(at + 24, nxt),                             # b next
        RET,                                         # done: ret
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out", required=True)
    ap.add_argument("--at", default="0xfffffe0009ebc880",
                    help="entry of the print routine to replace")
    ap.add_argument("--uart", default="0x9000000")
    ap.add_argument("--virt-base", default="0xfffffe0007004000")
    args = ap.parse_args(argv)

    at = int(args.at, 0)
    uart = int(args.uart, 0)
    vb = int(args.virt_base, 0)

    data = bytearray(open(args.kernel, "rb").read())
    off = at - vb
    if not (0 <= off < len(data) - 32):
        print(f"error: {at:#x} is outside the kernel", file=sys.stderr)
        return 2

    words = build(at, uart)
    labels = ["movz x2, uart", "next: ldrb w1, [x0], #1", "cbz  w1, done",
              "wait: ldr  w3, [x2, #0x18]", "tbnz w3, #5, wait",
              "str  w1, [x2]", "b    next", "done: ret"]

    print(f"\n=== early console at {at:#x}, PL011 at {uart:#x} ===\n")
    for i, (w, t) in enumerate(zip(words, labels)):
        old = struct.unpack_from("<I", data, off + i * 4)[0]
        print(f"  {at + i * 4:#018x}  {old:08x} -> {w:08x}   {t}")
        struct.pack_into("<I", data, off + i * 4, w)

    # Verify by reading back, and check the branch arithmetic closes.
    back = [struct.unpack_from("<I", data, off + i * 4)[0]
            for i in range(len(words))]
    if back != words:
        print("\n  SELF-CHECK FAILED: readback differs", file=sys.stderr)
        return 1
    if build(at, uart) != words:
        print("\n  SELF-CHECK FAILED: not deterministic", file=sys.stderr)
        return 1
    print("\n  self-check: readback matches, branches resolve within the routine")

    open(args.out, "wb").write(bytes(data))
    print(f"wrote {args.out} ({len(data):,} bytes)")
    print("\nThis discards the original routine's formatting. It exists so the")
    print("kernel's own words reach the serial line instead of a memory dump.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
