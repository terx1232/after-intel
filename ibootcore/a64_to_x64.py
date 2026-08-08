#!/usr/bin/env python3
"""
a64_to_x64.py -- a static arm64 -> x86-64 translator, and an honest measurement
of how far static translation gets on a real kernel.

This exists because "translate the kernel to x86" deserves working code rather
than an opinion. It decodes arm64 instructions and emits x86-64 for the ones
that have a meaning-preserving equivalent, and it reports precisely what it
cannot do and why.

Register model
--------------
arm64 has 31 general registers; x86-64 has 16. The mapping below assigns the
first 14 arm64 registers to host registers and spills the rest to a register
file in memory addressed through r15. Spilled operands cost a load and a store
around each instruction, which is normal for this kind of translator.

    x0->rax  x1->rbx  x2->rcx  x3->rdx  x4->rsi  x5->rdi  x6->rbp
    x7->r8   x8->r9   x9->r10  x10->r11 x11->r12 x12->r13 x13->r14
    x14..x30, sp, pc  ->  [r15 + n*8]

What this deliberately does not attempt
---------------------------------------
Instructions that configure the machine rather than compute: MSR/MRS, TLBI,
DC/IC, ERET, and the exception vector model. Those are not missing
substitutions -- they program ARM page tables, ARM exception vectors and ARM
cache semantics, none of which exist on x86 in a form any instruction sequence
can stand in for. See the coverage report for what that costs in practice.

Usage:
    python a64_to_x64.py --selftest
    python a64_to_x64.py --kernel vma2.kernel --at 0x2e38480 --count 40
    python a64_to_x64.py --kernel vma2.kernel --coverage
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter

# arm64 register -> x86-64 register, or a spill slot in the guest register file.
#
# Thirteen guest registers get host registers. rbp is deliberately NOT mapped:
# it is the scratch register, because x86 cannot encode a memory-to-memory move
# and any instruction with two spilled operands needs somewhere to stage one.
# r15 holds the base of the register file; rsp stays the host stack.
XREG = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14"]
SPILL_BASE = "r15"
SCRATCH = "rbp"


def hostreg(n: int) -> str:
    """Host location for arm64 register n."""
    if n == 31:
        return f"[{SPILL_BASE}+0xf8]"   # sp / xzr, disambiguated by the caller
    if n < len(XREG):
        return XREG[n]
    return f"[{SPILL_BASE}+{n * 8:#x}]"


def is_mem(loc: str) -> bool:
    return loc.startswith("[")


# --------------------------------------------------------------------------
# Shadow system register file.
#
# Guest system registers live in memory past the GPR spill area, addressed off
# the same base. Slots are assigned on first use and remembered, so the layout
# is stable for a given translation run and a helper runtime can be generated
# against it.
# --------------------------------------------------------------------------

SYSREG_BASE = 0x200          # GPR file occupies 0x00..0xf8
_sysreg_slots: dict = {}


def sysreg_slot(key: tuple) -> int:
    if key not in _sysreg_slots:
        _sysreg_slots[key] = SYSREG_BASE + len(_sysreg_slots) * 8
    return _sysreg_slots[key]


SYSREG_NAMES = {
    (3, 0, 13, 0, 4): "TPIDR_EL1",
    (3, 3, 14, 0, 2): "CNTVCT_EL0",
    (3, 3, 4, 2, 1): "DAIF",
    (3, 0, 1, 0, 0): "SCTLR_EL1",
    (3, 0, 2, 0, 0): "TTBR0_EL1",
    (3, 0, 2, 0, 1): "TTBR1_EL1",
    (3, 0, 2, 0, 2): "TCR_EL1",
    (3, 0, 12, 0, 0): "VBAR_EL1",
    (3, 0, 10, 2, 0): "MAIR_EL1",
    (3, 0, 1, 0, 2): "CPACR_EL1",
    (3, 0, 4, 1, 0): "SP_EL0",
    (3, 0, 4, 0, 0): "SPSR_EL1",
    (3, 0, 4, 0, 1): "ELR_EL1",
    (3, 0, 4, 2, 0): "SPSel",
}

# Writes that change how the machine addresses or dispatches. Everything else
# is state the guest reads back later and nothing more.
SYSREG_SIDE_EFFECTS = {
    "TTBR0_EL1": "rebuild shadow page tables",
    "TTBR1_EL1": "rebuild shadow page tables",
    "TCR_EL1": "granule and address size changed",
    "SCTLR_EL1": "MMU/cache enable",
    "VBAR_EL1": "exception vector base -> host IDT",
    "MAIR_EL1": "memory attributes",
    "CPACR_EL1": "FP/SIMD trapping",
    "SPSel": "stack pointer selection",
    "DAIF": "interrupt masking -> cli/sti",
    "SP_EL0": "the other stack pointer",
    "ELR_EL1": "exception return address",
    "SPSR_EL1": "saved processor state",
}


def move(dst: str, src: str) -> list:
    """Emit a move, staging through the scratch register when both are memory."""
    if dst == src:
        return []
    if is_mem(dst) and is_mem(src):
        return [f"mov  {SCRATCH}, {src}", f"mov  {dst}, {SCRATCH}"]
    return [f"mov  {dst}, {src}"]


def sextract(value: int, lo: int, width: int) -> int:
    v = (value >> lo) & ((1 << width) - 1)
    if v & (1 << (width - 1)):
        v -= 1 << width
    return v


class Unsupported(Exception):
    def __init__(self, category: str, why: str):
        super().__init__(why)
        self.category = category
        self.why = why


def translate(w: int, pc: int) -> tuple:
    """Translate one arm64 word. Returns (mnemonic, [x86 lines]).

    Raises Unsupported for instructions with no meaning-preserving equivalent.
    """
    # ---- system registers: a shadow file, not a wall ----------------------
    #
    # Calling every MSR/MRS untranslatable was too coarse. A census of this
    # kernel (sysreg_census.py) finds 10,082 accesses of which 10,028 are
    # reads or writes of registers that hold state and nothing more --
    # TPIDR_EL1 alone accounts for 8,120 reads. Against a shadow register file
    # in memory those are ordinary loads and stores.
    #
    # Only writes that change how the machine addresses or dispatches need a
    # runtime callback, and there are 54 of those in the whole kernel.
    if (w & 0xFFF00000) in (0xD5100000, 0xD5300000):
        is_read = (w & 0xFFF00000) == 0xD5300000
        op0 = 2 + ((w >> 19) & 1)
        op1 = (w >> 16) & 7
        crn = (w >> 12) & 0xF
        crm = (w >> 8) & 0xF
        op2 = (w >> 5) & 7
        rt = w & 0x1F
        key = (op0, op1, crn, crm, op2)
        name = SYSREG_NAMES.get(key)

        # The counter is real hardware state, not stored state: x86 has its own.
        if is_read and name == "CNTVCT_EL0":
            dst = hostreg(rt)
            return "mrs", [
                "rdtsc                      ; CNTVCT_EL0 -> host timestamp",
                "shl  rdx, 32",
                "or   rax, rdx",
            ] + (move(dst, "rax") if dst != "rax" else [])

        if not is_read and name in SYSREG_SIDE_EFFECTS:
            src = hostreg(rt)
            return "msr", [
                f"mov  rdi, {src}",
                f"call sysreg_write_{name}    ; {SYSREG_SIDE_EFFECTS[name]}",
            ]

        slot = sysreg_slot(key)
        loc = f"[{SPILL_BASE}+{slot:#x}]"
        label = name or f"S{op0}_{op1}_C{crn}_C{crm}_{op2}"
        if is_read:
            dst = hostreg(rt)
            if is_mem(dst):
                return "mrs", [f"mov  {SCRATCH}, {loc}   ; {label}",
                               f"mov  {dst}, {SCRATCH}"]
            return "mrs", [f"mov  {dst}, {loc}   ; {label}"]
        src = hostreg(rt)
        if is_mem(src):
            return "msr", [f"mov  {SCRATCH}, {src}",
                           f"mov  {loc}, {SCRATCH}   ; {label}"]
        return "msr", [f"mov  {loc}, {src}   ; {label}"]
    # ---- TLB and cache maintenance ----------------------------------------
    # x86 caches are coherent, so most of the data-cache operations a kernel
    # issues to keep memory and cache in step have nothing to do on the host
    # and become no-ops. TLB invalidation does have to happen, but through the
    # shadow mapping rather than the guest's, so it goes to the runtime.
    if (w & 0xFFF80000) == 0xD5080000:
        crn = (w >> 12) & 0xF
        rt = w & 0x1F
        if crn == 8:
            return "tlbi", [f"mov  rdi, {hostreg(rt)}",
                            "call runtime_tlbi          ; invalidate shadow mapping"]
        if crn == 7:
            return "dc/ic", ["; dc/ic -> no-op (x86 caches are coherent)"]
        return "sys", ["call runtime_sys"]

    # ---- exception model ---------------------------------------------------
    # These do not map to an x86 instruction, but they do map to a call. The
    # runtime holds the shadow SPSR and ELR and knows how the guest's exception
    # levels are being represented on the host.
    if w == 0xD69F03E0:
        return "eret", ["call runtime_eret         ; restore from shadow SPSR/ELR"]
    if (w & 0xFFE0001F) == 0xD4000001:
        return "svc", [f"mov  rdi, {(w >> 5) & 0xFFFF:#x}", "call runtime_svc"]
    if (w & 0xFFE0001F) == 0xD4000002:
        return "hvc", [f"mov  rdi, {(w >> 5) & 0xFFFF:#x}", "call runtime_hvc"]
    if (w & 0xFFE0001F) == 0xD4000003:
        return "smc", [f"mov  rdi, {(w >> 5) & 0xFFFF:#x}", "call runtime_smc"]

    # ---- barriers: the favourable direction ------------------------------
    if (w & 0xFFFFF0FF) == 0xD503309F:
        return "dsb", ["mfence"]
    if (w & 0xFFFFF0FF) == 0xD50330BF:
        return "dmb", ["; dmb -> no-op (x86 is strongly ordered)"]
    if (w & 0xFFFFF0FF) == 0xD50330DF:
        return "isb", ["; isb -> no-op (x86 serialises on branch)"]

    # ---- pointer authentication ------------------------------------------
    # In a whole-system translation the translator owns both signing and
    # authentication, so PAC can be made the identity. These become no-ops,
    # and authenticated branches become ordinary indirect branches.
    if (w & 0xFFFFF01F) == 0xD503201F:
        crm_op2 = (w >> 5) & 0x7F
        if 0x18 <= crm_op2 <= 0x1F or 0x38 <= crm_op2 <= 0x3F:
            return "pac/aut", ["; pac/aut -> no-op (PAC modelled as identity)"]
        return "nop", ["nop"]
    if (w & 0xFFFE0000) == 0xDAC10000:
        return "pac/aut", ["; pac/aut -> no-op (PAC modelled as identity)"]
    if w in (0xD65F0BFF, 0xD65F0FFF):
        return "retaa/retab", ["ret"]
    if (w & 0xFE1FF800) == 0xD61F0800:
        rn = (w >> 5) & 0x1F
        link = (w >> 21) & 1
        op = "call" if link else "jmp"
        # Use the scratch register, not a mapped one: rdi now holds guest x5.
        return ("blraa" if link else "braa",
                [f"mov  {SCRATCH}, {hostreg(rn)}",
                 f"and  {SCRATCH}, 0x0000ffffffffffff   ; strip PAC bits",
                 f"{op} [guest_dispatch + {SCRATCH}*8]  ; via translation map"])

    # ---- ordinary control flow -------------------------------------------
    if (w & 0xFC000000) == 0x14000000:
        target = pc + (sextract(w, 0, 26) << 2)
        return "b", [f"jmp  L_{target:x}"]
    if (w & 0xFC000000) == 0x94000000:
        target = pc + (sextract(w, 0, 26) << 2)
        return "bl", [f"call L_{target:x}"]
    if w == 0xD65F03C0:
        return "ret", ["ret"]
    if (w & 0xFFFFFC1F) == 0xD61F0000:
        rn = (w >> 5) & 0x1F
        return "br", [f"jmp  [guest_dispatch + {hostreg(rn)}*8]"]
    if (w & 0xFF000010) == 0x54000000:
        cond = w & 0xF
        target = pc + (sextract(w, 5, 19) << 2)
        cc = ["e", "ne", "b", "ae", "s", "ns", "o", "no",
              "a", "be", "ge", "l", "g", "le", "mp", "mp"][cond]
        return "b.cond", [f"j{cc}  L_{target:x}"]

    # ---- data processing (immediate) -------------------------------------
    sf = (w >> 31) & 1
    if (w & 0x7F800000) == 0x11000000:      # ADD (immediate)
        rd, rn, imm = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0xFFF
        if (w >> 22) & 1:
            imm <<= 12
        if rd == rn:
            return "add", [f"add  {hostreg(rd)}, {imm:#x}"]
        return "add", move(hostreg(rd), hostreg(rn)) + [
            f"add  {hostreg(rd)}, {imm:#x}"]
    if (w & 0x7F800000) == 0x51000000:      # SUB (immediate)
        rd, rn, imm = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0xFFF
        if (w >> 22) & 1:
            imm <<= 12
        if rd == rn:
            return "sub", [f"sub  {hostreg(rd)}, {imm:#x}"]
        return "sub", move(hostreg(rd), hostreg(rn)) + [
            f"sub  {hostreg(rd)}, {imm:#x}"]
    if (w & 0x7F800000) == 0x71000000:      # SUBS (immediate) == CMP
        rn, imm = (w >> 5) & 0x1F, (w >> 10) & 0xFFF
        return "cmp", [f"cmp  {hostreg(rn)}, {imm:#x}"]
    # MOVZ/MOVK: the sf bit is bit 31, so the comparison value must be the
    # opcode with that bit already masked off -- 0xD2800000 & 0x7F800000 is
    # 0x52800000, not 0xD2800000. Getting this wrong makes the test
    # unsatisfiable and every MOVZ falls through as undecoded.
    if (w & 0x7F800000) == 0x52800000:      # MOVZ
        rd, imm, hw = w & 0x1F, (w >> 5) & 0xFFFF, (w >> 21) & 3
        return "movz", [f"mov  {hostreg(rd)}, {imm << (16 * hw):#x}"]
    if (w & 0x7F800000) == 0x72800000:      # MOVK
        rd, imm, hw = w & 0x1F, (w >> 5) & 0xFFFF, (w >> 21) & 3
        mask = ~(0xFFFF << (16 * hw)) & 0xFFFFFFFFFFFFFFFF
        return "movk", [f"and  {hostreg(rd)}, {mask:#x}",
                        f"or   {hostreg(rd)}, {imm << (16 * hw):#x}"]

    # ---- PC-relative address formation ------------------------------------
    # ADR/ADRP are how arm64 forms addresses at all, so they are everywhere.
    # Both fold to a constant here because the translation is static and the
    # guest address is known at translate time.
    if (w & 0x9F000000) in (0x10000000, 0x90000000):
        rd = w & 0x1F
        immlo = (w >> 29) & 3
        immhi = (w >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        if w & 0x80000000:                       # ADRP: page-aligned
            target = ((pc & ~0xFFF) + (imm << 12)) & 0xFFFFFFFFFFFFFFFF
            mn = "adrp"
        else:
            target = (pc + imm) & 0xFFFFFFFFFFFFFFFF
            mn = "adr"
        dst = hostreg(rd)
        if is_mem(dst):
            return mn, [f"mov  {SCRATCH}, {target:#x}", f"mov  {dst}, {SCRATCH}"]
        return mn, [f"mov  {dst}, {target:#x}"]

    # ---- data processing, register form -----------------------------------
    # `sf opc S 01011 shift N Rm imm6 Rn Rd` for add/sub, 01010 for logical.
    # Only the unshifted forms are handled: a shifted operand needs a scratch
    # to hold the shifted value, and those are a small minority.
    if (w & 0x1F000000) in (0x0B000000, 0x0A000000):
        logical = (w & 0x1F000000) == 0x0A000000
        opc = (w >> 29) & 3
        shift = (w >> 22) & 3
        imm6 = (w >> 10) & 0x3F
        rm, rn, rd = (w >> 16) & 0x1F, (w >> 5) & 0x1F, w & 0x1F
        if shift or imm6:
            raise Unsupported("undecoded",
                              "shifted-register form needs a scratch operand")
        names = (("and", "orr", "eor", "ands") if logical
                 else ("add", "adds", "sub", "subs"))
        x86op = (("and", "or", "xor", "and") if logical
                 else ("add", "add", "sub", "sub"))[opc]
        mn = names[opc]

        # MOV Xd, Xm is ORR Xd, XZR, Xm -- extremely common, worth its own path
        if logical and opc == 1 and rn == 31:
            return "mov", move(hostreg(rd), hostreg(rm))
        # CMP is SUBS with Rd == XZR; CMN is ADDS with Rd == XZR
        if rd == 31 and opc in (1, 3):
            a, b_ = hostreg(rn), hostreg(rm)
            if is_mem(a) and is_mem(b_):
                return ("cmp" if not logical else "tst",
                        [f"mov  {SCRATCH}, {a}", f"cmp  {SCRATCH}, {b_}"])
            return ("cmp" if not logical else "tst", [f"cmp  {a}, {b_}"])

        out = []
        dst, src = hostreg(rd), hostreg(rm)
        if rd != rn:
            out += move(dst, hostreg(rn))
        if is_mem(dst) and is_mem(src):
            out += [f"mov  {SCRATCH}, {src}", f"{x86op:<4} {dst}, {SCRATCH}"]
        else:
            out.append(f"{x86op:<4} {dst}, {src}")
        return mn, out

    # ---- loads and stores -------------------------------------------------
    # Unsigned-offset load/store, all four operand sizes:
    #   `size 111 V 01 opc imm12 Rn Rt`, V=0 for the integer register file.
    # The scale of imm12 is the access size, which is what `size` selects.
    if (w & 0x3B000000) == 0x39000000 and not ((w >> 26) & 1):
        size = (w >> 30) & 3
        opc = (w >> 22) & 3
        rt, rn = w & 0x1F, (w >> 5) & 0x1F
        imm = ((w >> 10) & 0xFFF) << size
        width = {0: "byte", 1: "word", 2: "dword", 3: "qword"}[size]
        movsz = {0: "movzx", 1: "movzx", 2: "mov", 3: "mov"}[size]
        base, pre = hostreg(rn), []
        if is_mem(base):
            pre, base = [f"mov  {SCRATCH}, {base}"], SCRATCH
        mem = f"{width} [{base}+{imm:#x}]"

        if opc == 0:                                   # store
            src = hostreg(rt)
            if is_mem(src):
                return "str", pre + [f"mov  {SCRATCH}, {src}",
                                     f"mov  {mem}, {SCRATCH}"]
            return "str", pre + [f"mov  {mem}, {src}"]

        dst = hostreg(rt)                              # load
        if is_mem(dst):
            return "ldr", pre + [f"{movsz} {SCRATCH}, {mem}",
                                 f"mov  {dst}, {SCRATCH}"]
        return "ldr", pre + [f"{movsz} {dst}, {mem}"]
    if (w & 0xFFC00000) == 0xA9800000 or (w & 0xFFC00000) == 0xA9000000:
        rt, rn, rt2 = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0x1F
        imm = sextract(w, 15, 7) * 8
        base, out = hostreg(rn), []
        if is_mem(base):
            out.append(f"mov  {SCRATCH}, {base}")
            base = SCRATCH
        for slot, r in ((imm, rt), (imm + 8, rt2)):
            src = hostreg(r)
            if is_mem(src):
                # base already occupies SCRATCH when it was spilled, so stage
                # the value through the stack rather than clobbering it.
                out += [f"push {src}", f"pop  qword [{base}+{slot:#x}]"]
            else:
                out.append(f"mov  [{base}+{slot:#x}], {src}")
        return "stp", out
    if (w & 0xFFC00000) == 0xA9400000 or (w & 0xFFC00000) == 0xA8C00000:
        rt, rn, rt2 = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0x1F
        imm = sextract(w, 15, 7) * 8
        base, out = hostreg(rn), []
        if is_mem(base):
            out.append(f"mov  {SCRATCH}, {base}")
            base = SCRATCH
        for slot, r in ((imm, rt), (imm + 8, rt2)):
            dst = hostreg(r)
            if is_mem(dst):
                out += [f"push qword [{base}+{slot:#x}]", f"pop  {dst}"]
            else:
                out.append(f"mov  {dst}, [{base}+{slot:#x}]")
        return "ldp", out

    if w == 0:
        return "(zero)", ["; padding"]

    raise Unsupported("undecoded",
                      "not in this translator's subset (NEON, atomics, "
                      "bitfield, extended-register forms, ...)")


def selftest() -> int:
    """Translate known encodings and check the output is what it should be."""
    cases = [
        (0xD2820000, 0, "movz", "mov  rax, 0x1000"),
        (0xD61F0020, 0, "br",   "jmp  [guest_dispatch + rbx*8]"),
        (0xD65F03C0, 0, "ret",  "ret"),
        (0x91000400, 0, "add",  "add  rax, 0x1"),
        (0xD503201F, 0, "nop",  "nop"),
    ]
    ok = True
    print("translating known encodings:\n")
    for w, pc, want_mn, want_first in cases:
        try:
            mn, lines = translate(w, pc)
        except Unsupported as e:
            print(f"  {w:08x}  UNSUPPORTED ({e.category})")
            ok = False
            continue
        good = mn == want_mn and lines[0].strip() == want_first
        print(f"  {w:08x}  {mn:<10} -> {lines[0]:<40} "
              f"{'ok' if good else 'MISMATCH, wanted ' + want_first}")
        ok &= good
    print("\n  " + ("PASS" if ok else "FAILED"))
    return 0 if ok else 1


def coverage(path: str, limit: int = 0) -> dict:
    b = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", b, 16)[0]
    off = 32
    fileoff = size = 0
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == 0x19:
            name = b[off + 8:off + 24].split(b"\x00")[0]
            if name == b"__TEXT_EXEC":
                _va, _vs, fileoff, size = struct.unpack_from("<QQQQ", b, off + 24)
        off += cmdsize
    n = size // 4
    if limit:
        n = min(n, limit)

    translated = Counter()
    failed = Counter()
    reasons = {}
    for i in range(n):
        (w,) = struct.unpack_from("<I", b, fileoff + i * 4)
        try:
            mn, _ = translate(w, i * 4)
            translated[mn] += 1
        except Unsupported as e:
            failed[e.category] += 1
            reasons.setdefault(e.category, e.why)
    return {"instructions": n, "translated": dict(translated.most_common()),
            "failed": dict(failed.most_common()), "reasons": reasons,
            "translated_total": sum(translated.values()),
            "failed_total": sum(failed.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--kernel")
    ap.add_argument("--at", help="file offset to start disassembling")
    ap.add_argument("--count", type=int, default=32)
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.kernel:
        ap.print_help()
        return 1

    if args.coverage:
        r = coverage(args.kernel, args.limit)
        n = r["instructions"]
        print(f"\n=== static translation coverage: "
              f"{os.path.basename(args.kernel)} ===\n")
        print(f"instructions examined : {n:,}")
        print(f"translated            : {r['translated_total']:,} "
              f"({100.0 * r['translated_total'] / n:.2f}%)")
        print(f"not translated        : {r['failed_total']:,} "
              f"({100.0 * r['failed_total'] / n:.2f}%)\n")
        print(f"{'reason':<20}{'count':>12}{'share':>9}")
        print("-" * 44)
        for k, v in r["failed"].items():
            print(f"{k:<20}{v:>12,}{100.0 * v / n:>8.2f}%")
        print("\nwhy each is not a substitution:")
        for k, why in r["reasons"].items():
            if k != "undecoded":
                print(f"  {k}:\n      {why}")
        print("\ntop translated forms:")
        for k, v in list(r["translated"].items())[:14]:
            print(f"    {k:<14}{v:>12,}")
        if args.json:
            json.dump(r, open(args.json, "w", encoding="utf-8"), indent=2)
            print(f"\nwrote {args.json}", file=sys.stderr)
        return 0

    b = open(args.kernel, "rb").read()
    at = int(args.at, 0) if args.at else 0
    print(f"\n=== translating {args.count} instructions at {at:#x} ===\n")
    for i in range(args.count):
        (w,) = struct.unpack_from("<I", b, at + i * 4)
        try:
            mn, lines = translate(w, i * 4)
            print(f"  {w:08x}  {mn:<12} {lines[0]}")
            for extra in lines[1:]:
                print(f"  {'':8}  {'':<12} {extra}")
        except Unsupported as e:
            print(f"  {w:08x}  {'[' + e.category + ']':<12} {e.why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
