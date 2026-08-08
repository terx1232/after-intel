#!/usr/bin/env python3
"""
asm64.py -- a very small x86-64 assembler with labels.

Hand-encoding worked for the boot sector, where the whole program was forty
instructions and every jump was a byte away. It stops working the moment there
are subroutines and forward references, and the two bugs the boot sector shipped
with -- a missing operand-size prefix and REX.B where REX.R was meant -- were
both encoding mistakes that a table would not have made.

So: an emitter with named labels, two-pass fixups, and one function per
instruction form actually used. Not a general assembler; it covers exactly what
the monitor needs and refuses everything else loudly.
"""

from __future__ import annotations

import struct

REG = {"rax": 0, "rcx": 1, "rdx": 2, "rbx": 3, "rsp": 4, "rbp": 5,
       "rsi": 6, "rdi": 7, "r8": 8, "r9": 9, "r10": 10, "r11": 11,
       "r12": 12, "r13": 13, "r14": 14, "r15": 15}
REG8 = {"al": 0, "cl": 1, "dl": 2, "bl": 3}

CC = {"e": 0x4, "z": 0x4, "ne": 0x5, "nz": 0x5, "b": 0x2, "c": 0x2,
      "ae": 0x3, "nc": 0x3, "be": 0x6, "a": 0x7, "l": 0xC, "ge": 0xD,
      "le": 0xE, "g": 0xF, "s": 0x8, "ns": 0x9}


class Asm:
    def __init__(self, origin: int = 0):
        self.buf = bytearray()
        self.origin = origin
        self.labels: dict[str, int] = {}
        self.fixups: list = []          # (offset, size, label, kind)

    # -- bookkeeping -------------------------------------------------------

    def label(self, name: str) -> "Asm":
        if name in self.labels:
            raise ValueError(f"duplicate label {name!r}")
        self.labels[name] = len(self.buf)
        return self

    def here(self) -> int:
        return self.origin + len(self.buf)

    def _rel32(self, name: str):
        self.fixups.append((len(self.buf), 4, name, "rel"))
        self.buf += b"\x00\x00\x00\x00"

    def _abs64(self, name: str):
        self.fixups.append((len(self.buf), 8, name, "abs"))
        self.buf += b"\x00" * 8

    def link(self) -> bytes:
        for off, size, name, kind in self.fixups:
            if name not in self.labels:
                raise KeyError(f"undefined label {name!r}")
            target = self.labels[name]
            if kind == "rel":
                struct.pack_into("<i", self.buf, off, target - (off + 4))
            else:
                struct.pack_into("<Q", self.buf, off, self.origin + target)
        return bytes(self.buf)

    # -- encoding helpers --------------------------------------------------

    @staticmethod
    def _rex(w=0, r=0, x=0, b=0) -> bytes:
        v = 0x40 | (w << 3) | (r << 2) | (x << 1) | b
        return bytes([v])

    def _emit(self, *parts) -> "Asm":
        for p in parts:
            self.buf += p if isinstance(p, (bytes, bytearray)) else bytes([p])
        return self

    # -- instructions ------------------------------------------------------

    def mov_imm(self, reg: str, imm: int) -> "Asm":
        n = REG[reg]
        return self._emit(self._rex(w=1, b=n >> 3), 0xB8 + (n & 7),
                          struct.pack("<Q", imm & 0xFFFFFFFFFFFFFFFF))

    def mov_label(self, reg: str, name: str) -> "Asm":
        n = REG[reg]
        self._emit(self._rex(w=1, b=n >> 3), 0xB8 + (n & 7))
        self._abs64(name)
        return self

    def mov_rr(self, dst: str, src: str) -> "Asm":
        d, s = REG[dst], REG[src]
        return self._emit(self._rex(w=1, r=s >> 3, b=d >> 3), 0x89,
                          0xC0 | ((s & 7) << 3) | (d & 7))

    @staticmethod
    def _modrm_mem(reg_field: int, base: str, disp: int):
        """ModRM bytes for [base + disp].

        Two traps live here and both bit once already. rm == 101 with mod == 0
        does not mean [rbp], it means RIP-relative, so rbp and r13 always need
        an explicit zero displacement. And rm == 100 means a SIB byte follows,
        so rsp and r12 cannot be encoded this way at all.
        """
        b = REG[base]
        if (b & 7) == 4:
            raise ValueError(f"{base} as a base needs a SIB byte; not supported")
        if disp == 0 and (b & 7) == 5:
            disp = 0                      # force the disp8 form below
            mod, dbytes = 0x40, b"\x00"
        elif disp:
            mod, dbytes = 0x40, bytes([disp & 0xFF])
        else:
            mod, dbytes = 0x00, b""
        return bytes([mod | ((reg_field & 7) << 3) | (b & 7)]) + dbytes

    def mov_load(self, dst: str, base: str, disp: int = 0) -> "Asm":
        d, b = REG[dst], REG[base]
        return self._emit(self._rex(w=1, r=d >> 3, b=b >> 3), 0x8B,
                          self._modrm_mem(d, base, disp))

    def mov_store(self, base: str, src: str, disp: int = 0) -> "Asm":
        s, b = REG[src], REG[base]
        return self._emit(self._rex(w=1, r=s >> 3, b=b >> 3), 0x89,
                          self._modrm_mem(s, base, disp))

    def mov8_store(self, base: str, src8: str, disp: int = 0) -> "Asm":
        s, b = REG8[src8], REG[base]
        pre = self._rex(b=b >> 3) if b >> 3 else b""
        return self._emit(pre, 0x88, self._modrm_mem(s, base, disp))

    def mov8_load(self, dst8: str, base: str, disp: int = 0) -> "Asm":
        d, b = REG8[dst8], REG[base]
        pre = self._rex(b=1) if b >> 3 else b""
        return self._emit(pre, 0x8A, self._modrm_mem(d, base, disp))

    def cmp8_mem_imm(self, base: str, imm: int, disp: int = 0) -> "Asm":
        b = REG[base]
        pre = self._rex(b=1) if b >> 3 else b""
        return self._emit(pre, 0x80, self._modrm_mem(7, base, disp),
                          imm & 0xFF)

    def inc(self, reg: str) -> "Asm":
        n = REG[reg]
        return self._emit(self._rex(w=1, b=n >> 3), 0xFF, 0xC0 | (n & 7))

    def dec(self, reg: str) -> "Asm":
        n = REG[reg]
        return self._emit(self._rex(w=1, b=n >> 3), 0xFF, 0xC8 | (n & 7))

    def movzx8(self, dst: str, src8: str) -> "Asm":
        d, s = REG[dst], REG8[src8]
        return self._emit(self._rex(w=1, r=d >> 3), 0x0F, 0xB6,
                          0xC0 | ((d & 7) << 3) | s)

    def alu_imm(self, op: str, reg: str, imm: int) -> "Asm":
        codes = {"add": 0, "or": 1, "adc": 2, "sbb": 3,
                 "and": 4, "sub": 5, "xor": 6, "cmp": 7}
        n = REG[reg]
        return self._emit(self._rex(w=1, b=n >> 3), 0x81,
                          0xC0 | (codes[op] << 3) | (n & 7),
                          struct.pack("<i", imm))

    def alu_rr(self, op: str, dst: str, src: str) -> "Asm":
        codes = {"add": 0x01, "or": 0x09, "and": 0x21,
                 "sub": 0x29, "xor": 0x31, "cmp": 0x39}
        d, s = REG[dst], REG[src]
        return self._emit(self._rex(w=1, r=s >> 3, b=d >> 3), codes[op],
                          0xC0 | ((s & 7) << 3) | (d & 7))

    def shift_imm(self, op: str, reg: str, count: int) -> "Asm":
        codes = {"shl": 4, "shr": 5, "sar": 7, "rol": 0, "ror": 1}
        n = REG[reg]
        return self._emit(self._rex(w=1, b=n >> 3), 0xC1,
                          0xC0 | (codes[op] << 3) | (n & 7), count & 0xFF)

    def cmp8_imm(self, reg8: str, imm: int) -> "Asm":
        # 3C ib is the short form and only exists for al; everything else needs
        # the general 80 /7 ib encoding.
        if reg8 == "al":
            return self._emit(0x3C, imm & 0xFF)
        return self._emit(0x80, 0xF8 | REG8[reg8], imm & 0xFF)

    def test8_imm(self, reg8: str, imm: int) -> "Asm":
        if reg8 != "al":
            raise ValueError("only al supported")
        return self._emit(0xA8, imm & 0xFF)

    def in_al(self, port: int) -> "Asm":
        return self._emit(0xE4, port)

    def jmp(self, name: str) -> "Asm":
        self._emit(0xE9)
        self._rel32(name)
        return self

    def jcc(self, cond: str, name: str) -> "Asm":
        self._emit(0x0F, 0x80 + CC[cond])
        self._rel32(name)
        return self

    def call(self, name: str) -> "Asm":
        self._emit(0xE8)
        self._rel32(name)
        return self

    def call_mem(self, base: str, disp: int = 0) -> "Asm":
        """call qword [base + disp] -- FF /2."""
        b = REG[base]
        pre = self._rex(b=1) if b >> 3 else b""
        return self._emit(pre, 0xFF, self._modrm_mem(2, base, disp))

    def call_reg(self, reg: str) -> "Asm":
        n = REG[reg]
        pre = self._rex(b=1) if n >> 3 else b""
        return self._emit(pre, 0xFF, 0xD0 | (n & 7))

    def ret(self) -> "Asm":
        return self._emit(0xC3)

    def push(self, reg: str) -> "Asm":
        n = REG[reg]
        pre = self._rex(b=1) if n >> 3 else b""
        return self._emit(pre, 0x50 + (n & 7))

    def pop(self, reg: str) -> "Asm":
        n = REG[reg]
        pre = self._rex(b=1) if n >> 3 else b""
        return self._emit(pre, 0x58 + (n & 7))

    def nop(self) -> "Asm":
        return self._emit(0x90)

    def hlt(self) -> "Asm":
        return self._emit(0xF4)

    def raw(self, data: bytes) -> "Asm":
        return self._emit(data)
