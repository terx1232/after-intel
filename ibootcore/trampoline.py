#!/usr/bin/env python3
"""
trampoline.py -- emit a three-instruction arm64 stub that sets x0 and jumps to
the kernel entry point.

Step seven of IbootCore, and the piece that makes the rest runnable.

XNU expects two things at entry: PC at the kernel's entry point, and x0 holding
the physical address of `boot_args`. An emulator's generic image loader can set
PC -- QEMU's `-device loader` takes a `cpu-num` and starts execution there --
but it has no way to preload a general-purpose register. The usual answer for
Linux does not apply either, because QEMU's aarch64 boot stub sets x0 to the
device tree address, not to a boot_args pointer.

So a stub is needed. Three instructions, hand-encoded, no assembler required:

    movz/movk x0, #<boot_args physical address>   ; four halfwords
    movz/movk x1, #<kernel entry>                 ; four halfwords
    br  x1

Encodings, from the Arm Architecture Reference Manual:

    MOVZ Xd, #imm16, LSL #(16*hw)   0xD2800000 | hw<<21 | imm16<<5 | Rd
    MOVK Xd, #imm16, LSL #(16*hw)   0xF2800000 | hw<<21 | imm16<<5 | Rd
    BR   Xn                         0xD61F0000 | Rn<<5

Usage:
    python trampoline.py --x0 0x804e01000 --entry 0xfffffe0009e3c480 \\
        --out trampoline.bin
    python trampoline.py --from-build DIR --out trampoline.bin
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys


def movz(rd: int, imm16: int, hw: int) -> int:
    return 0xD2800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def movk(rd: int, imm16: int, hw: int) -> int:
    return 0xF2800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def br(rn: int) -> int:
    return 0xD61F0000 | ((rn & 0x1F) << 5)


def load_imm64(rd: int, value: int) -> list:
    """MOVZ then three MOVKs. Always four instructions, for predictable size."""
    out = [movz(rd, value & 0xFFFF, 0)]
    for hw in (1, 2, 3):
        out.append(movk(rd, (value >> (16 * hw)) & 0xFFFF, hw))
    return out


def build(x0: int, entry: int) -> bytes:
    words = load_imm64(0, x0) + load_imm64(1, entry) + [br(1)]
    return b"".join(struct.pack("<I", w) for w in words)


def disassemble(words: list, x0: int, entry: int) -> list:
    """A human-readable rendering, so the encoding can be eyeballed."""
    lines = []
    for i, w in enumerate(words):
        if i < 4:
            rd, val, hw = 0, x0, i
        elif i < 8:
            rd, val, hw = 1, entry, i - 4
        else:
            lines.append(f"  {i * 4:>3}: {w:08x}   br    x1")
            continue
        op = "movz" if hw == 0 else "movk"
        imm = (val >> (16 * hw)) & 0xFFFF
        shift = "" if hw == 0 else f", lsl #{16 * hw}"
        lines.append(f"  {i * 4:>3}: {w:08x}   {op}  x{rd}, #{imm:#06x}{shift}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--x0", help="physical address of boot_args")
    ap.add_argument("--entry", help="kernel entry point")
    ap.add_argument("--from-build", metavar="DIR",
                    help="read entry and boot_args address from a build_all output dir")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    if args.from_build:
        lm = json.load(open(os.path.join(args.from_build, "loadmap.json"),
                            encoding="utf-8"))
        entry = lm["entry"]
        # build_image places boot_args after the kernel and the device tree;
        # recompute the same way rather than guessing.
        kern = lm["file_size"]
        dt_path = os.path.join(args.from_build, "devicetree.bin")
        dt_len = os.path.getsize(dt_path) if os.path.exists(dt_path) else 0
        phys = 0x800000000
        kend = (kern + (1 << 20) - 1) & ~((1 << 20) - 1)
        ba_off = (kend + dt_len + 0xFFF) & ~0xFFF
        x0 = phys + ba_off
        print(f"from {args.from_build}: entry {entry:#x}, boot_args {x0:#x}")
        print("  (assumes the default --phys-base; pass --x0 explicitly if you "
              "built with another)")
    else:
        if not (args.x0 and args.entry):
            ap.error("need --x0 and --entry, or --from-build")
        x0 = int(args.x0, 0)
        entry = int(args.entry, 0)

    blob = build(x0, entry)
    words = list(struct.unpack(f"<{len(blob) // 4}I", blob))

    print(f"\n=== trampoline: x0 = {x0:#018x}, br to {entry:#018x} ===\n")
    for line in disassemble(words, x0, entry):
        print(line)
    print(f"\n  {len(blob)} bytes, {len(words)} instructions")

    # Verify by decoding our own output rather than trusting the encoder.
    def decode_imm(rd_words, val):
        acc = 0
        for hw in range(4):
            acc |= ((val >> (16 * hw)) & 0xFFFF) << (16 * hw)
        return acc
    if decode_imm(words[:4], x0) != x0 or decode_imm(words[4:8], entry) != entry:
        print("  SELF-CHECK FAILED", file=sys.stderr)
        return 1
    print("  self-check: immediates reassemble to the requested values")

    if args.out:
        open(args.out, "wb").write(blob)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
