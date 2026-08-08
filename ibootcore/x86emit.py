#!/usr/bin/env python3
"""
x86emit.py -- encode x86-64 machine code, and build a BIOS-bootable image that
runs translated arm64 code natively.

The rest of IbootCore produces x86-64 as assembly text, which proves the
mapping but does not produce anything a CPU can fetch. This closes that gap: it
encodes instructions into bytes and wraps them in a boot sector that brings the
machine from BIOS real mode up to 64-bit long mode and jumps to the translated
code.

The point is to test the claim end to end. Under `-accel whpx` the host CPU
executes these bytes directly, with no translation of any kind, which is the
same thing that would happen booting from a disk on real hardware.

Layout of the produced image:

    0x7c00  boot sector: real mode -> protected mode -> long mode
    0x7e00  64-bit payload: the translated routine, then the result printer
    0x1000  PML4    built at runtime, identity maps the first 2 MiB
    0x2000  PDPT
    0x3000  PD (one 2 MiB page)
    0xb8000 VGA text buffer, where the result is printed

Usage:
    python x86emit.py --selftest
    python x86emit.py --demo --out boot.img
"""

from __future__ import annotations

import argparse
import struct
import sys

# ---------------------------------------------------------------------------
# minimal x86-64 encoder: only the forms this needs, each hand-checked
# ---------------------------------------------------------------------------

REG64 = {"rax": 0, "rcx": 1, "rdx": 2, "rbx": 3,
         "rsp": 4, "rbp": 5, "rsi": 6, "rdi": 7,
         "r8": 8, "r9": 9, "r10": 10, "r11": 11,
         "r12": 12, "r13": 13, "r14": 14, "r15": 15}


def rex(w=0, r=0, x=0, b=0) -> bytes:
    v = 0x40 | (w << 3) | (r << 2) | (x << 1) | b
    return bytes([v])


def mov_r64_imm64(reg: str, imm: int) -> bytes:
    n = REG64[reg]
    return rex(w=1, b=n >> 3) + bytes([0xB8 + (n & 7)]) + struct.pack("<Q", imm)


def mov_r64_r64(dst: str, src: str) -> bytes:
    d, s = REG64[dst], REG64[src]
    return rex(w=1, r=s >> 3, b=d >> 3) + b"\x89" + bytes([0xC0 | ((s & 7) << 3) | (d & 7)])


def add_r64_imm32(reg: str, imm: int) -> bytes:
    n = REG64[reg]
    return rex(w=1, b=n >> 3) + b"\x81" + bytes([0xC0 | (n & 7)]) + struct.pack("<i", imm)


def sub_r64_imm32(reg: str, imm: int) -> bytes:
    n = REG64[reg]
    return rex(w=1, b=n >> 3) + b"\x81" + bytes([0xE8 | (n & 7)]) + struct.pack("<i", imm)


def cmp_r64_imm32(reg: str, imm: int) -> bytes:
    n = REG64[reg]
    return rex(w=1, b=n >> 3) + b"\x81" + bytes([0xF8 | (n & 7)]) + struct.pack("<i", imm)


def add_r64_r64(dst: str, src: str) -> bytes:
    d, s = REG64[dst], REG64[src]
    return rex(w=1, r=s >> 3, b=d >> 3) + b"\x01" + bytes([0xC0 | ((s & 7) << 3) | (d & 7)])


def jmp_rel8(off: int) -> bytes:
    return b"\xeb" + struct.pack("<b", off)


def jne_rel8(off: int) -> bytes:
    return b"\x75" + struct.pack("<b", off)


def ret() -> bytes:
    return b"\xc3"


def hlt() -> bytes:
    return b"\xf4"


# ---------------------------------------------------------------------------
# the demo routine, in arm64, translated by hand through the same mapping
# a64_to_x64.py uses: x0->rax, x1->rbx, x2->rcx
# ---------------------------------------------------------------------------

ARM64_DEMO = [
    (0xD2800000, "movz x0, #0        ; accumulator"),
    (0xD2800141, "movz x1, #10       ; counter"),
    (0x8B010000, "add  x0, x0, x1    ; acc += counter"),
    (0xD1000421, "sub  x1, x1, #1"),
    (0xF100003F, "cmp  x1, #0"),
    (0x54FFFF81, "b.ne -3            ; loop"),
    (0xD65F03C0, "ret"),
]


def translated_demo() -> bytes:
    """The same computation, emitted as x86-64 bytes.

    Sums 10 down to 1, which is 55 (0x37). Register mapping follows
    a64_to_x64.py: guest x0 -> rax, x1 -> rbx.
    """
    body = bytearray()
    body += mov_r64_imm64("rax", 0)       # x0 = 0
    body += mov_r64_imm64("rbx", 10)      # x1 = 10
    loop = len(body)
    body += add_r64_r64("rax", "rbx")     # x0 += x1
    body += sub_r64_imm32("rbx", 1)       # x1 -= 1
    body += cmp_r64_imm32("rbx", 0)       # cmp x1, #0
    here = len(body)
    body += jne_rel8(0)                   # placeholder
    disp = loop - (here + 2)
    body[here:here + 2] = jne_rel8(disp)
    # The arm64 original ends in `ret`, and the translation of `ret` is `ret`.
    # There is no caller here though -- the boot sector jumps straight in -- so
    # returning would pop whatever happens to be on the stack. Fall through to
    # the printer instead, which is what a translator would do when it can see
    # that the return goes nowhere.
    return bytes(body)


def print_rax_hex() -> bytes:
    """Write rax as 16 hex digits into the VGA text buffer at 0xb8000."""
    out = bytearray()
    out += mov_r64_imm64("rdi", 0xB8000)
    out += mov_r64_imm64("rcx", 16)
    # rdx = rax, we rotate it left 4 bits at a time
    out += mov_r64_r64("rdx", "rax")
    loop_start = len(out)
    # rol rdx, 4
    out += rex(w=1) + b"\xc1\xc2\x04"
    # mov r8, rdx ; and r8, 0xf
    # REX.B extends the r/m field, which is the destination here. REX.R extends
    # reg instead, which turned this into `mov rax, r10` and quietly destroyed
    # the value being printed.
    out += rex(w=1, b=1) + b"\x89\xd0"          # mov r8, rdx
    out += rex(w=1, b=1) + b"\x83\xe0\x0f"      # and r8, 0xf
    # cmp r8, 9 ; jbe digit
    out += rex(w=1, b=1) + b"\x83\xf8\x09"      # cmp r8, 9
    out += b"\x77\x06"                          # ja +6  (letter)
    out += rex(w=1, b=1) + b"\x83\xc0\x30"      # add r8, '0'
    out += b"\xeb\x04"                          # jmp +4
    out += rex(w=1, b=1) + b"\x83\xc0\x37"      # add r8, 'A'-10
    # store character and attribute
    out += rex(w=0, r=1) + b"\x88\x07"          # mov [rdi], r8b
    out += b"\xc6\x47\x01\x0a"                  # mov byte [rdi+1], 0x0a (green)
    out += rex(w=1) + b"\x83\xc7\x02"           # add rdi, 2
    out += rex(w=1) + b"\x83\xe9\x01"           # sub rcx, 1
    here = len(out)
    out += b"\x75\x00"                          # jnz placeholder
    out[here + 1] = (loop_start - (here + 2)) & 0xFF
    return bytes(out)


def build_boot_image() -> bytes:
    """Boot sector: real -> protected -> long mode, then run the payload."""
    # --- 16-bit boot sector -------------------------------------------------
    b = bytearray()
    b += b"\xfa"                                   # cli
    b += b"\x31\xc0"                               # xor ax, ax
    b += b"\x8e\xd8\x8e\xc0\x8e\xd0"               # mov ds/es/ss, ax
    b += b"\xbc\x00\x7c"                           # mov sp, 0x7c00

    # zero 0x1000..0x4000 for the page tables
    b += b"\xb8\x00\x01"                           # mov ax, 0x100
    b += b"\x8e\xc0"                               # mov es, ax     (es = 0x1000)
    b += b"\x31\xff"                               # xor di, di
    b += b"\xb9\x00\x18"                           # mov cx, 0x1800 (3 * 2048 words)
    b += b"\x31\xc0"                               # xor ax, ax
    b += b"\xf3\xab"                               # rep stosw

    # PML4[0] = 0x2000 | 3
    b += b"\x31\xff"                               # xor di, di
    b += b"\xb8\x03\x20"                           # mov ax, 0x2003
    b += b"\x26\x89\x05"                           # mov [es:di], ax
    # PDPT[0] = 0x3000 | 3   (es:0x1000)
    b += b"\xbf\x00\x10"                           # mov di, 0x1000
    b += b"\xb8\x03\x30"                           # mov ax, 0x3003
    b += b"\x26\x89\x05"                           # mov [es:di], ax
    # PD[0] = 0 | 0x83  (2 MiB page, present, rw, PS)
    b += b"\xbf\x00\x20"                           # mov di, 0x2000
    b += b"\xb8\x83\x00"                           # mov ax, 0x0083
    b += b"\x26\x89\x05"                           # mov [es:di], ax

    # load GDT
    gdt_off = None
    b += b"\x0f\x01\x16"                           # lgdt [imm16]
    gdt_off = len(b)
    b += b"\x00\x00"                               # patched below

    # NOTE on the 0x66 prefixes below. This is still 16-bit code, so the
    # default operand size is 16 bits: `b9 80 00 00 c0` assembles as
    # `mov cx, 0x0080` followed by garbage, not `mov ecx, 0xc0000080`. Every
    # instruction here that needs a 32-bit immediate or accumulator has to
    # carry the operand-size prefix explicitly. Leaving it off is why the first
    # version of this boot sector never reached long mode.
    #
    # `0f 20`/`0f 22` (mov to/from control registers) are exempt: they are
    # always 32-bit in 16-bit mode and take no prefix.

    # CR4.PAE
    b += b"\x0f\x20\xe0"                           # mov eax, cr4
    b += b"\x0c\x20"                               # or al, 0x20
    b += b"\x0f\x22\xe0"                           # mov cr4, eax
    # CR3 = 0x1000
    b += b"\x66\xb8\x00\x10\x00\x00"               # mov eax, 0x1000
    b += b"\x0f\x22\xd8"                           # mov cr3, eax
    # EFER.LME
    b += b"\x66\xb9\x80\x00\x00\xc0"               # mov ecx, 0xc0000080
    b += b"\x0f\x32"                               # rdmsr
    # EFER.LME is bit 8, not bit 0. `or al, 1` sets SCE (SYSCALL enable) and
    # leaves long mode off, after which CR0.PG with PAE selects 32-bit PAE
    # paging instead: a three-level walk over tables built for four levels,
    # which mapped only the first 4 KiB and page-faulted on the next
    # instruction fetch. Set bit 8 via ah.
    b += b"\x80\xcc\x01"                           # or ah, 1
    b += b"\x0f\x30"                               # wrmsr
    # CR0.PG | CR0.PE
    b += b"\x0f\x20\xc0"                           # mov eax, cr0
    b += b"\x66\x0d\x01\x00\x00\x80"               # or eax, 0x80000001
    b += b"\x0f\x22\xc0"                           # mov cr0, eax
    # far jump to 64-bit
    b += b"\x66\xea"                               # jmp far dword
    far_off = len(b)
    b += b"\x00\x00\x00\x00"                       # offset, patched
    b += b"\x08\x00"                               # selector 0x08

    # --- GDT ----------------------------------------------------------------
    while len(b) % 8:
        b += b"\x00"
    gdt_addr = 0x7C00 + len(b)
    gdt = (struct.pack("<Q", 0)
           + struct.pack("<Q", 0x00AF9A000000FFFF)   # 64-bit code
           + struct.pack("<Q", 0x00CF92000000FFFF))  # data
    b += gdt
    gdtr_addr = 0x7C00 + len(b)
    b += struct.pack("<HI", len(gdt) - 1, gdt_addr)
    struct.pack_into("<H", b, gdt_off, gdtr_addr)

    # --- 64-bit payload -----------------------------------------------------
    while len(b) < 0x140:
        b += b"\x00"
    payload_addr = 0x7C00 + len(b)
    struct.pack_into("<I", b, far_off, payload_addr)

    pay = bytearray()
    pay += translated_demo()      # leaves the result in rax
    pay += print_rax_hex()
    pay += hlt()
    pay += jmp_rel8(-2)           # park
    b += pay

    if len(b) > 510:
        raise ValueError(f"boot sector overflows: {len(b)} bytes")
    b += b"\x00" * (510 - len(b))
    b += b"\x55\xaa"
    return bytes(b)


def selftest() -> int:
    print("arm64 source of the demo routine:\n")
    for w, txt in ARM64_DEMO:
        print(f"    {w:08x}   {txt}")
    x = translated_demo()
    print(f"\ntranslated to x86-64: {len(x)} bytes")
    print("   ", x.hex(" "))
    print("\nexpected result: 10+9+...+1 = 55 = 0x37")
    img = build_boot_image()
    print(f"\nboot image: {len(img)} bytes, signature "
          f"{img[510]:02x}{img[511]:02x}")
    return 0 if img[510:512] == b"\x55\xaa" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.demo:
        img = build_boot_image()
        out = args.out or "boot.img"
        # pad to a floppy-ish size so BIOS is happy
        open(out, "wb").write(img + b"\x00" * (1474560 - len(img)))
        print(f"wrote {out}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
