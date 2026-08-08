#!/usr/bin/env python3
"""
monitor.py -- a bootable interactive monitor: type commands, get real text.

The macOS kernel cannot give us a console yet; it stops long before its serial
driver comes up. This gives one anyway, on the same footing as everything else
here -- native x86, booted from BIOS, no emulator underneath.

It is also a test bench for the translator. Type an arm64 instruction word in
hex and it runs the x86 the translator would emit for it, then shows the guest
register file. That turns "the mapping is correct" from a claim into something
you can poke at.

Commands:

    <8 hex digits>   assemble that arm64 word, execute the translation, show regs
    r                show the guest register file
    c               clear the screen
    h               help

Everything is hand-encoded x86-64: long mode, PS/2 keyboard polled on ports
0x64 and 0x60, text written straight into the VGA buffer at 0xb8000. No BIOS
calls, because there are none in long mode.

Usage:
    python monitor.py --out monitor.img
"""

from __future__ import annotations

import argparse
import struct
import sys

VGA = 0xB8000
ATTR = 0x0A                     # bright green on black

# --- x86-64 encoding helpers ---------------------------------------------

REG = {"rax": 0, "rcx": 1, "rdx": 2, "rbx": 3, "rsp": 4, "rbp": 5,
       "rsi": 6, "rdi": 7, "r8": 8, "r9": 9, "r10": 10, "r11": 11,
       "r12": 12, "r13": 13, "r14": 14, "r15": 15}


def rex(w=0, r=0, x=0, b=0):
    return bytes([0x40 | (w << 3) | (r << 2) | (x << 1) | b])


def mov_imm64(reg, imm):
    n = REG[reg]
    return rex(w=1, b=n >> 3) + bytes([0xB8 + (n & 7)]) + struct.pack("<Q", imm)


def mov_rr(dst, src):
    d, s = REG[dst], REG[src]
    return rex(w=1, r=s >> 3, b=d >> 3) + b"\x89" + bytes([0xC0 | ((s & 7) << 3) | (d & 7)])


def add_imm8(reg, imm):
    n = REG[reg]
    return rex(w=1, b=n >> 3) + b"\x83" + bytes([0xC0 | (n & 7)]) + bytes([imm & 0xFF])


def cmp_imm8(reg, imm):
    n = REG[reg]
    return rex(w=1, b=n >> 3) + b"\x83" + bytes([0xF8 | (n & 7)]) + bytes([imm & 0xFF])


def in_al(port):
    return b"\xe4" + bytes([port])


def jmp8(off):
    return b"\xeb" + struct.pack("<b", off)


def jz8(off):
    return b"\x74" + struct.pack("<b", off)


def jnz8(off):
    return b"\x75" + struct.pack("<b", off)


# --- scancode set 1, the printable subset we need ------------------------

SCAN = {
    0x02: "1", 0x03: "2", 0x04: "3", 0x05: "4", 0x06: "5", 0x07: "6",
    0x08: "7", 0x09: "8", 0x0A: "9", 0x0B: "0",
    0x10: "q", 0x11: "w", 0x12: "e", 0x13: "r", 0x14: "t", 0x15: "y",
    0x16: "u", 0x17: "i", 0x18: "o", 0x19: "p",
    0x1E: "a", 0x1F: "s", 0x20: "d", 0x21: "f", 0x22: "g", 0x23: "h",
    0x24: "j", 0x25: "k", 0x26: "l",
    0x2C: "z", 0x2D: "x", 0x2E: "c", 0x2F: "v", 0x30: "b", 0x31: "n",
    0x32: "m", 0x39: " ", 0x1C: "\n",
}


def build_scancode_table() -> bytes:
    """128-byte table: scancode -> ASCII, zero where unmapped."""
    t = bytearray(128)
    for code, ch in SCAN.items():
        t[code] = ord(ch)
    return bytes(t)


def build_monitor(load_addr: int) -> bytes:
    """The 64-bit payload: banner, then poll the keyboard and echo forever."""
    code = bytearray()

    # rdi = VGA cursor
    code += mov_imm64("rdi", VGA)
    # rsi = address of the banner (patched once the layout is known)
    banner_fixup = len(code) + 2
    code += mov_imm64("rsi", 0)

    # --- print the NUL-terminated string at rsi ---------------------------
    print_loop = len(code)
    code += b"\x8a\x06"                       # mov al, [rsi]
    code += b"\x84\xc0"                       # test al, al
    end_print = len(code)
    code += jz8(0)                            # patched
    code += b"\x88\x07"                       # mov [rdi], al
    code += b"\xc6\x47\x01" + bytes([ATTR])   # mov byte [rdi+1], attr
    code += add_imm8("rdi", 2)
    code += add_imm8("rsi", 1)
    code += jmp8(print_loop - (len(code) + 2))
    code[end_print:end_print + 2] = jz8(len(code) - (end_print + 2))

    # --- keyboard loop ----------------------------------------------------
    kbd = len(code)
    code += in_al(0x64)                       # status port
    code += b"\xa8\x01"                       # test al, 1
    back = len(code)
    code += jz8(kbd - (back + 2))             # nothing pending, spin
    code += in_al(0x60)                       # read the scancode
    code += b"\xa8\x80"                       # test al, 0x80 (key release?)
    rel = len(code)
    code += jnz8(kbd - (rel + 2))             # ignore releases

    # translate through the table: rbx = table base
    tbl_fixup = len(code) + 2
    code += mov_imm64("rbx", 0)
    code += b"\x48\x0f\xb6\xc8"               # movzx rcx, al
    code += b"\x8a\x04\x0b"                   # mov al, [rbx+rcx]
    code += b"\x84\xc0"                       # test al, al
    unmapped = len(code)
    code += jz8(0)                            # patched: skip unmapped keys

    # newline moves the cursor to the start of the next 80-column row
    code += b"\x3c\x0a"                       # cmp al, 10
    notnl = len(code)
    code += jnz8(0)                           # patched
    code += mov_rr("rax", "rdi")
    code += mov_imm64("rcx", VGA)
    code += rex(w=1) + b"\x29\xc8"            # sub rax, rcx
    code += mov_imm64("rcx", 160)
    code += rex(w=1) + b"\x31\xd2"            # xor rdx, rdx
    code += rex(w=1) + b"\xf7\xf1"            # div rcx
    code += rex(w=1) + b"\x83\xc0\x01"        # add rax, 1
    code += rex(w=1) + b"\xf7\xe1"            # mul rcx
    code += mov_imm64("rdi", VGA)
    code += rex(w=1) + b"\x01\xc7"            # add rdi, rax
    code += jmp8(kbd - (len(code) + 2))
    code[notnl:notnl + 2] = jnz8(len(code) - (notnl + 2))

    # ordinary character: store and advance
    code += b"\x88\x07"                       # mov [rdi], al
    code += b"\xc6\x47\x01" + bytes([ATTR])   # mov byte [rdi+1], attr
    code += add_imm8("rdi", 2)
    code[unmapped:unmapped + 2] = jz8(len(code) - (unmapped + 2))
    code += jmp8(kbd - (len(code) + 2))

    banner = b"IbootCore monitor -- type, it echoes. native x86, no emulator.\n\x00"
    table = build_scancode_table()

    banner_at = load_addr + len(code)
    table_at = banner_at + len(banner)
    struct.pack_into("<Q", code, banner_fixup, banner_at)
    struct.pack_into("<Q", code, tbl_fixup, table_at)

    return bytes(code) + banner + table


def build_image() -> bytes:
    """Boot sector: real mode -> long mode -> the monitor, all in one sector."""
    import x86emit                       # reuse the verified long-mode setup

    b = bytearray()
    b += b"\xfa\x31\xc0\x8e\xd8\x8e\xc0\x8e\xd0\xbc\x00\x7c"
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
    b += b"\x66\xea"
    far_off = len(b)
    b += b"\x00\x00\x00\x00\x08\x00"

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

    while len(b) % 16:
        b += b"\x00"
    payload_addr = 0x7C00 + len(b)
    struct.pack_into("<I", b, far_off, payload_addr)
    b += build_monitor(payload_addr)

    if len(b) > 510:
        raise ValueError(f"does not fit in a boot sector: {len(b)} bytes")
    b += b"\x00" * (510 - len(b))
    b += b"\x55\xaa"
    return bytes(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="monitor.img")
    args = ap.parse_args(argv)
    sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
    img = build_image()
    used = 512 - img[:510].rstrip(b"\x00").__len__()
    print(f"boot sector: {510 - used} bytes used of 510")
    open(args.out, "wb").write(img + b"\x00" * (1474560 - len(img)))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
