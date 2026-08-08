#!/usr/bin/env python3
"""
monitor2.py -- the monitor with commands: a translator test bench on bare metal.

The point is to check the translator against a real CPU rather than against my
reading of the Arm manual. You type an arm64 instruction word in hex, the
monitor runs the x86 that a64_to_x64.py produced for it, and prints the guest
register file. If the mapping is wrong the registers say so.

Commands:

    <8 hex digits>   run the translation of that arm64 word
    r                print the guest register file
    l                list the words that have translations built in
    c                clear the screen
    h                help

The translations are produced at build time -- there is no Python on the target
-- and embedded as x86 blocks with a lookup table in front of them.

Layout: the boot sector loads the rest of the image with INT 13h while still in
real mode, then goes to long mode and jumps to the monitor at 0x8000.

Usage:
    python monitor2.py --out monitor2.img
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from asm64 import Asm                      # noqa: E402

VGA = 0xB8000
ATTR = 0x0A
MONITOR_ORG = 0x8000
GUEST_REGS = 0x20000          # r15 points here: the guest register file
LINE_BUF   = 0x21000          # the typed line, NUL-terminated
BLOCK_SLOT = 0x80             # where the block address parks, past x0..x15

# arm64 words the bench knows, with what they should do to the guest state.
DEMO_WORDS = [
    (0xD2800141, "movz x1, #10"),
    (0xD2801002, "movz x2, #128"),
    (0x8B020020, "add  x0, x1, x2"),
    (0xCB020020, "sub  x0, x1, x2"),
    (0xAA0203E3, "mov  x3, x2"),
    (0xD2800000, "movz x0, #0"),
    (0x91000421, "add  x1, x1, #1"),
    (0xD1000421, "sub  x1, x1, #1"),
]

SCAN = {
    0x02: "1", 0x03: "2", 0x04: "3", 0x05: "4", 0x06: "5", 0x07: "6",
    0x08: "7", 0x09: "8", 0x0A: "9", 0x0B: "0",
    0x10: "q", 0x11: "w", 0x12: "e", 0x13: "r", 0x14: "t", 0x15: "y",
    0x16: "u", 0x17: "i", 0x18: "o", 0x19: "p",
    0x1E: "a", 0x1F: "s", 0x20: "d", 0x21: "f", 0x22: "g", 0x23: "h",
    0x24: "j", 0x25: "k", 0x26: "l",
    0x2C: "z", 0x2D: "x", 0x2E: "c", 0x2F: "v", 0x30: "b", 0x31: "n",
    0x32: "m", 0x39: " ", 0x1C: "\n", 0x0E: "\b",
    # Without these the xN=HEX command cannot be typed at all: the first
    # attempt turned "x1=5" into "x15" and reported a bad line.
    0x0D: "=", 0x0C: "-", 0x27: ";", 0x34: ".",
}


def scancode_table() -> bytes:
    t = bytearray(128)
    for c, ch in SCAN.items():
        t[c] = ord(ch)
    return bytes(t)


def translate_word(word: int) -> bytes:
    """Assemble the x86 the translator emits for one arm64 word.

    Only the forms the demo set uses are encoded; anything else is refused
    rather than guessed at, which is the same rule the translator follows.
    """
    import a64_to_x64 as T
    mn, lines = T.translate(word, 0)
    a = Asm()
    for line in lines:
        line = line.split(";")[0].strip()
        if not line:
            continue
        op, _, rest = line.partition(" ")
        args = [x.strip() for x in rest.split(",")] if rest else []
        if op == "mov" and len(args) == 2:
            dst, src = args
            if src.startswith("["):
                a.mov_load(dst, "r15", int(src.strip("[]").split("+")[1], 16))
            elif dst.startswith("["):
                a.mov_store("r15", src, int(dst.strip("[]").split("+")[1], 16))
            elif src.startswith("0x") or src.isdigit():
                a.mov_imm(dst, int(src, 0))
            else:
                a.mov_rr(dst, src)
        elif op in ("add", "sub", "and", "or", "xor", "cmp") and len(args) == 2:
            dst, src = args
            if src.startswith("0x") or src.lstrip("-").isdigit():
                a.alu_imm(op, dst, int(src, 0))
            else:
                a.alu_rr(op, dst, src)
        else:
            raise ValueError(f"bench cannot encode: {line!r}")
    a.ret()
    return a.link()


def build_monitor() -> bytes:
    a = Asm(origin=MONITOR_ORG)

    # r15 = guest register file, rdi = VGA cursor
    a.mov_imm("r15", GUEST_REGS)
    a.mov_imm("rdi", VGA)
    a.mov_label("rsi", "s_banner")
    a.call("puts")

    # Input is line-based rather than per-keystroke. The first version
    # dispatched on each character, which made c, r, l and h both commands and
    # hex digits, so half the instruction words could not be typed at all.
    a.label("prompt")
    a.mov_label("rsi", "s_prompt")
    a.call("puts")
    a.mov_imm("r13", LINE_BUF)             # r13 = write position

    a.label("readkey")
    a.call("getkey")                       # -> al
    a.cmp8_imm("al", 0x0A)
    a.jcc("e", "line_done")
    a.cmp8_imm("al", 0x08)                 # backspace
    a.jcc("e", "do_backspace")
    a.mov8_store("r13", "al")
    a.inc("r13")
    a.call("putc")
    a.jmp("readkey")

    a.label("do_backspace")
    a.mov_rr("rax", "r13")
    a.mov_imm("rdx", LINE_BUF)
    a.alu_rr("cmp", "rax", "rdx")
    a.jcc("e", "readkey")                  # nothing to erase
    a.dec("r13")
    a.alu_imm("sub", "rdi", 2)
    a.mov_imm("rax", 0x20)
    a.mov8_store("rdi", "al")
    a.jmp("readkey")

    a.label("line_done")
    a.mov_imm("rax", 0)
    a.mov8_store("r13", "al")              # NUL-terminate
    a.call("newline")
    a.mov_imm("r11", LINE_BUF)             # r11 = parse cursor
    a.mov_rr("rax", "r13")
    a.mov_imm("rdx", LINE_BUF)
    a.alu_rr("sub", "rax", "rdx")
    a.mov_rr("r14", "rax")                 # r14 = length
    a.alu_imm("cmp", "r14", 0)
    a.jcc("e", "prompt")

    # one-character lines are commands
    a.alu_imm("cmp", "r14", 1)
    a.jcc("ne", "not_cmd")
    a.mov8_load("al", "r11")
    a.cmp8_imm("al", ord("r"))
    a.jcc("e", "cmd_regs")
    a.cmp8_imm("al", ord("h"))
    a.jcc("e", "cmd_help")
    a.cmp8_imm("al", ord("c"))
    a.jcc("e", "cmd_clear")
    a.cmp8_imm("al", ord("l"))
    a.jcc("e", "cmd_list")
    a.jmp("bad_line")

    a.label("not_cmd")
    # "xN=HHHH..." sets a guest register before running anything
    a.mov8_load("al", "r11")
    a.cmp8_imm("al", ord("x"))
    a.jcc("e", "cmd_set")
    # otherwise it should be a hex instruction word
    a.alu_imm("cmp", "r14", 8)
    a.jcc("ne", "bad_line")
    a.call("parse_hex")                    # r11 -> rax
    a.mov_rr("r12", "rax")
    a.call("run_word")
    a.jmp("prompt")

    a.label("bad_line")
    a.mov_label("rsi", "s_bad")
    a.call("puts")
    a.jmp("prompt")

    # --- xN=HEX -----------------------------------------------------------
    a.label("cmd_set")
    a.inc("r11")
    a.mov8_load("al", "r11")
    a.movzx8("rbx", "al")
    a.alu_imm("sub", "rbx", ord("0"))
    a.alu_imm("cmp", "rbx", 3)
    a.jcc("a", "bad_line")                 # only x0..x3 are displayed
    a.inc("r11")
    a.mov8_load("al", "r11")
    a.cmp8_imm("al", ord("="))
    a.jcc("ne", "bad_line")
    a.inc("r11")
    a.call("parse_hex")
    a.shift_imm("shl", "rbx", 3)
    a.alu_rr("add", "rbx", "r15")
    a.mov_store("rbx", "rax")
    a.call("dump_regs")
    a.jmp("prompt")

    # --- parse_hex: NUL-terminated hex at r11 -> rax -----------------------
    a.label("parse_hex")
    a.push("rcx")
    a.mov_imm("rax", 0)
    a.label("ph_next")
    a.mov8_load("cl", "r11")
    a.cmp8_imm("cl", 0)
    a.jcc("e", "ph_end")
    a.movzx8("rcx", "cl")
    a.alu_imm("sub", "rcx", ord("0"))
    a.alu_imm("cmp", "rcx", 9)
    a.jcc("be", "ph_digit")
    a.alu_imm("sub", "rcx", ord("a") - ord("0") - 10)
    a.label("ph_digit")
    a.shift_imm("shl", "rax", 4)
    a.alu_rr("or", "rax", "rcx")
    a.inc("r11")
    a.jmp("ph_next")
    a.label("ph_end")
    a.pop("rcx")
    a.ret()

    a.label("cmd_regs")
    a.call("newline")
    a.call("dump_regs")
    a.jmp("prompt")

    a.label("cmd_help")
    a.call("newline")
    a.mov_label("rsi", "s_help")
    a.call("puts")
    a.jmp("prompt")

    a.label("cmd_list")
    a.call("newline")
    a.mov_label("rsi", "s_list")
    a.call("puts")
    a.jmp("prompt")

    a.label("cmd_clear")
    a.mov_imm("rdi", VGA)
    a.mov_imm("rcx", 2000)
    a.label("clr_loop")
    a.mov_imm("rax", 0x0720)
    a.mov8_store("rdi", "al")
    a.alu_imm("add", "rdi", 2)
    a.alu_imm("sub", "rcx", 1)
    a.jcc("ne", "clr_loop")
    a.mov_imm("rdi", VGA)
    a.jmp("prompt")

    # --- run_word: look r12 up in the table and call its block ------------
    a.label("run_word")
    a.mov_label("rbx", "word_table")
    a.label("rw_loop")
    a.mov_load("rax", "rbx", 0)
    a.alu_imm("cmp", "rax", 0)
    a.jcc("e", "rw_unknown")
    a.alu_rr("cmp", "rax", "r12")
    a.jcc("e", "rw_found")
    a.alu_imm("add", "rbx", 16)
    a.jmp("rw_loop")

    a.label("rw_found")
    # The block address cannot stay in a register: every one of x0..x3 maps to
    # a host register that is about to be loaded from the shadow file. Park it
    # in memory and call indirectly through there.
    a.mov_load("rax", "rbx", 8)
    a.mov_store("r15", "rax", BLOCK_SLOT)

    # Load the guest state into the host registers the translator uses. Without
    # this the xN= command set values the block never saw, because the
    # translator keeps x0..x12 in host registers.
    a.mov_load("rdx", "r15", 24)           # x3
    a.mov_load("rcx", "r15", 16)           # x2
    a.mov_load("rbx", "r15", 8)            # x1
    a.mov_load("rax", "r15", 0)            # x0
    a.call_mem("r15", BLOCK_SLOT)

    # Spill the results back: the other half of the same round trip.
    a.mov_store("r15", "rax", 0)           # x0
    a.mov_store("r15", "rbx", 8)           # x1
    a.mov_store("r15", "rcx", 16)          # x2
    a.mov_store("r15", "rdx", 24)          # x3
    a.call("dump_regs")
    a.ret()

    a.label("rw_unknown")
    a.mov_label("rsi", "s_unknown")
    a.call("puts")
    a.ret()

    # --- dump_regs --------------------------------------------------------
    a.label("dump_regs")
    a.push("rbx")
    a.mov_imm("rbx", 0)
    a.label("dr_loop")
    a.mov_label("rsi", "s_x")
    a.call("puts")
    a.mov_rr("rax", "rbx")
    a.call("puthex2")
    a.mov_label("rsi", "s_eq")
    a.call("puts")
    a.mov_rr("rax", "rbx")
    a.shift_imm("shl", "rax", 3)
    a.alu_rr("add", "rax", "r15")
    a.mov_load("rax", "rax", 0)
    a.call("puthex16")
    a.call("newline")
    a.alu_imm("add", "rbx", 1)
    a.alu_imm("cmp", "rbx", 4)
    a.jcc("ne", "dr_loop")
    a.pop("rbx")
    a.ret()

    # --- output helpers ---------------------------------------------------
    a.label("puts")
    a.label("puts_loop")
    a.raw(b"\x8a\x06")                     # mov al, [rsi]
    a.raw(b"\x84\xc0")                     # test al, al
    a.jcc("e", "puts_done")
    a.alu_imm("add", "rsi", 1)
    a.push("rsi")
    a.call("putc")
    a.pop("rsi")
    a.jmp("puts_loop")
    a.label("puts_done")
    a.ret()

    a.label("putc")
    a.cmp8_imm("al", 0x0A)
    a.jcc("e", "putc_nl")
    a.mov8_store("rdi", "al")
    a.mov_imm("rax", ATTR)
    a.mov8_store("rdi", "al", 1)
    a.alu_imm("add", "rdi", 2)
    a.ret()
    a.label("putc_nl")
    a.label("newline")
    a.push("rax")
    a.push("rdx")
    a.mov_rr("rax", "rdi")
    a.mov_imm("rdx", VGA)
    a.alu_rr("sub", "rax", "rdx")
    a.mov_imm("rcx", 160)
    a.raw(b"\x48\x31\xd2")                 # xor rdx, rdx
    a.raw(b"\x48\xf7\xf1")                 # div rcx
    a.alu_imm("add", "rax", 1)
    a.raw(b"\x48\xf7\xe1")                 # mul rcx
    a.mov_imm("rdi", VGA)
    a.alu_rr("add", "rdi", "rax")
    a.pop("rdx")
    a.pop("rax")
    a.ret()

    a.label("puthex16")
    a.mov_imm("rcx", 16)
    a.jmp("ph_common")
    a.label("puthex2")
    a.mov_imm("rcx", 2)
    a.shift_imm("shl", "rax", 56)
    a.label("ph_common")
    a.mov_rr("rdx", "rax")
    a.label("ph_loop")
    a.shift_imm("rol", "rdx", 4)
    a.mov_rr("rax", "rdx")
    a.alu_imm("and", "rax", 0xF)
    a.alu_imm("cmp", "rax", 9)
    a.jcc("a", "ph_letter")
    a.alu_imm("add", "rax", ord("0"))
    a.jmp("ph_emit")
    a.label("ph_letter")
    a.alu_imm("add", "rax", ord("a") - 10)
    a.label("ph_emit")
    a.push("rcx")
    a.push("rdx")
    a.call("putc")
    a.pop("rdx")
    a.pop("rcx")
    a.alu_imm("sub", "rcx", 1)
    a.jcc("ne", "ph_loop")
    a.ret()

    # --- keyboard ---------------------------------------------------------
    a.label("getkey")
    a.in_al(0x64)
    a.test8_imm("al", 1)
    a.jcc("e", "getkey")
    a.in_al(0x60)
    a.test8_imm("al", 0x80)
    a.jcc("ne", "getkey")
    a.movzx8("rcx", "al")
    a.mov_label("rax", "scan_table")
    a.alu_rr("add", "rax", "rcx")
    a.raw(b"\x8a\x00")                     # mov al, [rax]
    a.cmp8_imm("al", 0)
    a.jcc("e", "getkey")
    a.ret()

    # --- data -------------------------------------------------------------
    def string(name, text):
        a.label(name)
        a.raw(text.encode("ascii") + b"\x00")

    string("s_banner", "IbootCore monitor. h for help.\n")
    string("s_prompt", "> ")
    string("s_help",
           "type 8 hex digits: run that arm64 word\n"
           "xN=HEX   set guest register x0..x3\n"
           "r regs   l list   c clear   h help\n")
    string("s_unknown", "no translation built in for that word\n")
    string("s_bad", "?  try h\n")
    string("s_x", "x")
    string("s_eq", " = ")
    listing = "".join(f"{w:08x}  {d}\n" for w, d in DEMO_WORDS)
    string("s_list", listing)

    a.label("scan_table")
    a.raw(scancode_table())

    # translated blocks, then the lookup table pointing at them
    blocks = {}
    for word, desc in DEMO_WORDS:
        try:
            code = translate_word(word)
        except Exception as e:
            print(f"  skip {word:08x} ({desc}): {e}", file=sys.stderr)
            continue
        a.label(f"blk_{word:08x}")
        a.raw(code)
        blocks[word] = f"blk_{word:08x}"

    a.label("word_table")
    for word, lbl in blocks.items():
        a.raw(struct.pack("<Q", word))
        a.fixups.append((len(a.buf), 8, lbl, "abs"))
        a.raw(b"\x00" * 8)
    a.raw(struct.pack("<QQ", 0, 0))        # terminator

    return a.link(), len(blocks)


def build_image() -> bytes:
    monitor, nblocks = build_monitor()
    sectors = (len(monitor) + 511) // 512

    b = bytearray()
    b += b"\xfa\x31\xc0\x8e\xd8\x8e\xc0\x8e\xd0\xbc\x00\x7c"
    # load `sectors` sectors starting at LBA 1 to 0x0000:0x8000
    b += b"\xb8\x00\x00\x8e\xc0"                       # mov ax,0 ; mov es,ax
    b += b"\xbb\x00\x80"                               # mov bx, 0x8000
    b += bytes([0xB4, 0x02])                           # mov ah, 2
    b += bytes([0xB0, sectors])                        # mov al, sectors
    b += b"\xb5\x00\xb1\x02\xb6\x00\xb2\x00"           # ch=0 cl=2 dh=0 dl=0
    b += b"\xcd\x13"                                   # int 13h
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
    b += b"\x66\xea" + struct.pack("<I", MONITOR_ORG) + b"\x08\x00"

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
    b += monitor + b"\x00" * (sectors * 512 - len(monitor))
    return bytes(b), sectors, nblocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="monitor2.img")
    args = ap.parse_args(argv)

    img, sectors, nblocks = build_image()
    print(f"stage 1 : boot sector, loads {sectors} sector(s)")
    print(f"monitor : {len(img) - 512} bytes at {MONITOR_ORG:#x}")
    print(f"blocks  : {nblocks} translated arm64 words built in")
    open(args.out, "wb").write(img + b"\x00" * (1474560 - len(img)))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
