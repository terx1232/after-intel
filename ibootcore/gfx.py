#!/usr/bin/env python3
"""
gfx.py -- the bench in graphics mode: run the suite and draw the result.

To be clear about what this is and is not. The macOS kernel does not reach
graphics: it stops on the paravirtual calls, and XNU brings its console and
framebuffer up well after that point. Nothing here draws anything of Apple's.

What it does draw is the translator's own test suite, on the bare machine, in
320x200 256-colour mode: a green bar for each case where the translated x86
agrees with the independent arm64 model, red where it does not. The suite is
the same one the text monitor runs; this renders it instead of printing it.

Mode 13h is set through the BIOS while still in real mode, because there are no
BIOS calls once long mode is on. After that the framebuffer at 0xa0000 is a
flat 320x200 byte array, one byte per pixel, which is about as simple as
graphics gets.

Usage:
    python gfx.py --out gfx.img
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from asm64 import Asm                                  # noqa: E402
import arm_model                                       # noqa: E402
from monitor2 import TEST_CASES, translate_word        # noqa: E402

FB = 0xA0000
W, H = 320, 200
ORG = 0x8000
REGS = 0x20000
SLOT = 0x80

# mode 13h palette entries that already exist: 2 green, 4 red, 15 white,
# 8 dark grey, 1 blue.
GREEN, RED, WHITE, GREY, BLUE = 2, 4, 15, 8, 1


def build_payload() -> bytes:
    a = Asm(origin=ORG)

    a.mov_imm("r15", REGS)

    # --- clear the screen to dark grey -----------------------------------
    a.mov_imm("rdi", FB)
    a.mov_imm("rcx", W * H)
    a.label("clr")
    a.mov_imm("rax", 0)
    a.mov8_store("rdi", "al")
    a.inc("rdi")
    a.alu_imm("sub", "rcx", 1)
    a.jcc("ne", "clr")

    # --- a title band across the top --------------------------------------
    a.mov_imm("rdi", FB)
    a.mov_imm("rcx", W * 8)
    a.label("band")
    a.mov_imm("rax", BLUE)
    a.mov8_store("rdi", "al")
    a.inc("rdi")
    a.alu_imm("sub", "rcx", 1)
    a.jcc("ne", "band")

    # --- run each case and draw its bar -----------------------------------
    a.mov_label("r10", "test_table")
    a.mov_imm("r13", 0)                      # case index

    a.label("loop")
    a.mov_load("rax", "r10", 0)
    a.alu_imm("cmp", "rax", 0)
    a.jcc("e", "done")

    a.mov_imm("rax", 0)
    a.mov_store("r15", "rax", 0)
    a.mov_store("r15", "rax", 24)
    a.mov_load("rax", "r10", 8)
    a.mov_store("r15", "rax", 8)
    a.mov_load("rax", "r10", 16)
    a.mov_store("r15", "rax", 16)

    a.mov_load("rax", "r10", 40)
    a.mov_store("r15", "rax", SLOT)
    a.mov_load("rdx", "r15", 24)
    a.mov_load("rcx", "r15", 16)
    a.mov_load("rbx", "r15", 8)
    a.mov_load("rax", "r15", 0)
    a.call_mem("r15", SLOT)
    a.mov_store("r15", "rax", 0)
    a.mov_store("r15", "rbx", 8)
    a.mov_store("r15", "rcx", 16)
    a.mov_store("r15", "rdx", 24)

    a.mov_load("rbx", "r10", 24)
    a.shift_imm("shl", "rbx", 3)
    a.alu_rr("add", "rbx", "r15")
    a.mov_load("rax", "rbx", 0)
    a.mov_load("rbx", "r10", 32)
    a.alu_rr("cmp", "rax", "rbx")
    a.mov_imm("r11", GREEN)
    a.jcc("e", "have_colour")
    a.mov_imm("r11", RED)
    a.label("have_colour")

    # bar: 14 rows tall starting at y = 16 + index*16, from x=16 to x=300
    a.mov_rr("rax", "r13")
    a.shift_imm("shl", "rax", 4)             # index * 16
    a.alu_imm("add", "rax", 16)              # + top margin
    a.mov_imm("rcx", W)
    a.raw(b"\x48\xf7\xe1")                   # mul rcx -> rax = y * 320
    a.mov_imm("rdi", FB)
    a.alu_rr("add", "rdi", "rax")
    a.alu_imm("add", "rdi", 16)              # left margin

    a.mov_imm("r9", 14)                      # rows
    a.label("row")
    a.push("rdi")
    a.mov_imm("rcx", 284)                    # bar width
    a.label("px")
    a.mov_rr("rax", "r11")
    a.mov8_store("rdi", "al")
    a.inc("rdi")
    a.alu_imm("sub", "rcx", 1)
    a.jcc("ne", "px")
    a.pop("rdi")
    a.alu_imm("add", "rdi", W)
    a.alu_imm("sub", "r9", 1)
    a.jcc("ne", "row")

    a.inc("r13")
    a.alu_imm("add", "r10", 48)
    a.jmp("loop")

    a.label("done")
    a.hlt()
    a.label("park")
    a.jmp("park")

    # --- data -------------------------------------------------------------
    blocks = {}
    for word, x1, x2, check, desc in TEST_CASES:
        try:
            code = translate_word(word)
        except Exception:
            continue
        a.label(f"b_{word:08x}")
        a.raw(code)
        blocks[word] = f"b_{word:08x}"

    a.label("test_table")
    for word, x1, x2, check, desc in TEST_CASES:
        if word not in blocks:
            continue
        expect = arm_model.step(word, {1: x1, 2: x2}).get(check, 0)
        a.raw(struct.pack("<QQQQQ", word, x1, x2, check, expect))
        a.fixups.append((len(a.buf), 8, blocks[word], "abs"))
        a.raw(b"\x00" * 8)
    a.raw(struct.pack("<Q", 0))

    return a.link(), len(blocks)


def build_image() -> bytes:
    payload, nblocks = build_payload()
    sectors = (len(payload) + 511) // 512

    b = bytearray()
    b += b"\xfa\x31\xc0\x8e\xd8\x8e\xc0\x8e\xd0\xbc\x00\x7c"
    # VGA mode 13h, while BIOS calls still exist
    b += b"\xb8\x13\x00\xcd\x10"
    # load the payload to 0x8000
    b += b"\xb8\x00\x00\x8e\xc0\xbb\x00\x80"
    b += bytes([0xB4, 0x02, 0xB0, sectors])
    b += b"\xb5\x00\xb1\x02\xb6\x00\xb2\x00\xcd\x13"
    # page tables
    b += b"\xb8\x00\x01\x8e\xc0\x31\xff\xb9\x00\x18\x31\xc0\xf3\xab"
    b += b"\x31\xff\xb8\x03\x20\x26\x89\x05"
    b += b"\xbf\x00\x10\xb8\x03\x30\x26\x89\x05"
    b += b"\xbf\x00\x20\xb8\x83\x00\x26\x89\x05"
    b += b"\x0f\x01\x16"
    gdt_off = len(b)
    b += b"\x00\x00"
    b += b"\x0f\x20\xe0\x0c\x20\x0f\x22\xe0"
    b += b"\x66\xb8\x00\x10\x00\x00\x0f\x22\xd8"
    b += b"\x66\xb9\x80\x00\x00\xc0\x0f\x32\x80\xcc\x01\x0f\x30"
    b += b"\x0f\x20\xc0\x66\x0d\x01\x00\x00\x80\x0f\x22\xc0"
    b += b"\x66\xea" + struct.pack("<I", ORG) + b"\x08\x00"

    while len(b) % 8:
        b += b"\x00"
    gdt_addr = 0x7C00 + len(b)
    gdt = (struct.pack("<Q", 0)
           + struct.pack("<Q", 0x00AF9A000000FFFF)
           + struct.pack("<Q", 0x00CF92000000FFFF))
    b += gdt
    gdtr_addr = 0x7C00 + len(b)
    b += struct.pack("<HI", len(gdt) - 1, gdt_addr)
    struct.pack_into("<H", b, gdt_off, gdtr_addr)

    if len(b) > 510:
        raise ValueError(f"stage 1 does not fit: {len(b)}")
    b += b"\x00" * (510 - len(b)) + b"\x55\xaa"
    b += payload + b"\x00" * (sectors * 512 - len(payload))
    return bytes(b), sectors, nblocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="gfx.img")
    args = ap.parse_args(argv)
    img, sectors, n = build_image()
    print(f"mode 13h, {W}x{H}x256")
    print(f"payload : {len(img) - 512} bytes, {sectors} sector(s)")
    print(f"cases   : {n} bars will be drawn")
    open(args.out, "wb").write(img + b"\x00" * (1474560 - len(img)))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
