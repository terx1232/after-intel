#!/usr/bin/env python3
"""
bochs_fb.py -- bring up a framebuffer before the kernel starts.

Everything this project has shown so far has been text on a serial line, because
there is no display at all: `boot_args.Video` points at an address QEMU has
nothing mapped at, so every pixel the kernel writes goes nowhere.

The job normally belongs to iBoot. On Apple Silicon iBoot programs the display
controller, draws the Apple logo, and hands the kernel a live framebuffer in
`boot_args`; the kernel then draws on top of what is already there. This project
replaces iBoot with a stub, and the stub drew nothing.

This emits the instructions that stub was missing, for QEMU's `bochs-display`
device - a plain PCI card with a linear framebuffer and the Bochs VBE registers,
and the least complicated display QEMU offers:

    BAR0   linear framebuffer, prefetchable
    BAR2   MMIO registers; the VBE registers are 16-bit at offset 0x500,
           indexed as 0x500 + index * 2

No firmware assigns BARs on `virt`, so the stub assigns them itself by writing
config space through ECAM, then enables memory decode, then programs the mode.
Config space for bus 0 is at ECAM + (device << 15).

A stated limitation: XNU on this architecture does not draw the Apple logo. That
bitmap lives in iBoot, not in the kernel, and iBoot is what this project does
not have. What the kernel does draw is its own text console - white on black, in
its built-in font - and, when not booted verbose, the progress indicator. So the
window shows a real Mac verbose boot rather than a logo. Drawing a logo would
mean this stub blitting one itself, which is decoration and nothing more.

Usage:
    python bochs_fb.py --fb 0x30000000 --mmio 0x32000000 --geometry 1024x768
"""

from __future__ import annotations

import argparse
import struct
import sys

# Bochs VBE register indices, from QEMU's hw/display/vga_int.h.
VBE_XRES, VBE_YRES, VBE_BPP, VBE_ENABLE = 1, 2, 3, 4
VBE_VIRT_WIDTH, VBE_VIRT_HEIGHT = 6, 7
VBE_X_OFFSET, VBE_Y_OFFSET = 8, 9

VBE_ENABLED = 0x01
VBE_LFB_ENABLED = 0x40

VBE_REGS_OFFSET = 0x500          # inside BAR2

CFG_COMMAND = 0x04
CFG_BAR0 = 0x10
CFG_BAR2 = 0x18
CMD_MEMORY = 0x02                # memory space decode


def movz64(rd, imm16, hw):
    return 0xD2800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def movk64(rd, imm16, hw):
    return 0xF2800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def movz32(rd, imm16, hw=0):
    return 0x52800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def movk32(rd, imm16, hw):
    return 0x72800000 | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)


def str_w(rt, rn, off):
    """STR Wt, [Xn, #off] -- unsigned offset, scaled by 4."""
    assert off % 4 == 0 and 0 <= off < 16384
    return 0xB9000000 | ((off // 4) << 10) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def strh_w(rt, rn, off):
    """STRH Wt, [Xn, #off] -- unsigned offset, scaled by 2."""
    assert off % 2 == 0 and 0 <= off < 8192
    return 0x79000000 | ((off // 2) << 10) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def str_w_post(rt, rn, imm9):
    """STR Wt, [Xn], #imm9 -- post-index."""
    return 0xB8000400 | ((imm9 & 0x1FF) << 12) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def subs_imm32(rd, rn, imm12):
    return 0x71000000 | ((imm12 & 0xFFF) << 10) | ((rn & 0x1F) << 5) | (rd & 0x1F)


def b_ne(pc, target):
    return 0x54000001 | ((((target - pc) // 4) & 0x7FFFF) << 5)


def load64(rd, value):
    out = [movz64(rd, value & 0xFFFF, 0)]
    for hw in (1, 2, 3):
        out.append(movk64(rd, (value >> (16 * hw)) & 0xFFFF, hw))
    return out


def load32(rd, value):
    return [movz32(rd, value & 0xFFFF, 0),
            movk32(rd, (value >> 16) & 0xFFFF, 1)]


def vbe(index):
    return VBE_REGS_OFFSET + index * 2


def build(ecam: int, device: int, fb: int, mmio: int,
          width: int, height: int, at: int = 0, fill: int | None = 0) -> list:
    """Instruction words that leave a live framebuffer at `fb`.

    `at` is where the sequence will be loaded, needed only to resolve the fill
    loop's backward branch.
    """
    cfg = ecam + (device << 15)
    words = []

    # x2 = this device's config space
    words += load64(2, cfg)
    # BAR0 = framebuffer, BAR2 = registers. The low bits of a BAR are type bits
    # and read back as such; writing the bare address is what firmware does.
    words += load32(3, fb)
    words.append(str_w(3, 2, CFG_BAR0))
    words += load32(4, mmio)
    words.append(str_w(4, 2, CFG_BAR2))
    # Enable memory decode. This is a 32-bit write covering Command and Status;
    # the status half is write-1-to-clear, so writing zeros there is harmless.
    words += load32(5, CMD_MEMORY)
    words.append(str_w(5, 2, CFG_COMMAND))

    # x6 = the VBE register block
    words += load64(6, mmio)
    # Mode changes are made with the display disabled, then re-enabled.
    words += load32(7, 0)
    words.append(strh_w(7, 6, vbe(VBE_ENABLE)))
    words += load32(7, width)
    words.append(strh_w(7, 6, vbe(VBE_XRES)))
    words.append(strh_w(7, 6, vbe(VBE_VIRT_WIDTH)))
    words += load32(7, height)
    words.append(strh_w(7, 6, vbe(VBE_YRES)))
    words.append(strh_w(7, 6, vbe(VBE_VIRT_HEIGHT)))
    words += load32(7, 32)
    words.append(strh_w(7, 6, vbe(VBE_BPP)))
    words += load32(7, 0)
    words.append(strh_w(7, 6, vbe(VBE_X_OFFSET)))
    words.append(strh_w(7, 6, vbe(VBE_Y_OFFSET)))
    words += load32(7, VBE_ENABLED | VBE_LFB_ENABLED)
    words.append(strh_w(7, 6, vbe(VBE_ENABLE)))

    # Paint the whole framebuffer. Black by default, because that is what a Mac
    # shows and the card no longer needs proving. Passing a colour turns this
    # back into a self-test: a screen that comes up in that colour says the
    # BARs, the mode and memory decode are all correct, which black cannot say
    # because it is indistinguishable from nothing working at all. That is how
    # this was first shown to work - 99.8% of a screendump came back
    # rgb(32,64,96), and the remaining 0.2% was the kernel's progress bar.
    if fill is not None:
        words += load64(8, fb)
        words += load32(9, fill)
        words += load32(10, width * height)
        loop = at + len(words) * 4
        words.append(str_w_post(9, 8, 4))
        words.append(subs_imm32(10, 10, 1))
        words.append(b_ne(at + len(words) * 4, loop))

    return words


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ecam", default="0x3f000000")
    ap.add_argument("--device", type=lambda s: int(s, 0), default=3)
    ap.add_argument("--fb", default="0x30000000")
    ap.add_argument("--mmio", default="0x32000000")
    ap.add_argument("--geometry", default="1024x768")
    ap.add_argument("--at", default="0x41000000")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    w, _, h = args.geometry.lower().partition("x")
    words = build(int(args.ecam, 0), args.device, int(args.fb, 0),
                  int(args.mmio, 0), int(w), int(h), at=int(args.at, 0))

    print(f"\n=== bochs-display bring-up ===\n")
    print(f"  ECAM          {int(args.ecam, 0):#x}, device {args.device} "
          f"-> config {int(args.ecam, 0) + (args.device << 15):#x}")
    print(f"  BAR0 fb       {int(args.fb, 0):#x}")
    print(f"  BAR2 regs     {int(args.mmio, 0):#x}, VBE at +{VBE_REGS_OFFSET:#x}")
    print(f"  mode          {w}x{h}x32")
    print(f"  {len(words)} instructions, {len(words) * 4} bytes")

    if args.out:
        blob = b"".join(struct.pack("<I", x) for x in words)
        open(args.out, "wb").write(blob)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

