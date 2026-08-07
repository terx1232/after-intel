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

# arm64 register -> x86-64 register name, or None if spilled to memory
XREG = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14"]
SPILL_BASE = "r15"


def hostreg(n: int) -> str:
    """Host location for arm64 register n."""
    if n == 31:
        return "[r15+0xf8]"        # sp / xzr handled by caller
    if n < len(XREG):
        return XREG[n]
    return f"[{SPILL_BASE}+{n * 8:#x}]"


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
    # ---- things that program the machine, not compute --------------------
    if (w & 0xFFF00000) == 0xD5100000:
        raise Unsupported("system_register",
                          "msr: writes TTBR/TCR/SCTLR/VBAR; x86 has CR3/IDT "
                          "with different table and vector formats")
    if (w & 0xFFF00000) == 0xD5300000:
        raise Unsupported("system_register",
                          "mrs: reads ARM system state that has no x86 analogue")
    if (w & 0xFFF80000) == 0xD5080000:
        crn = (w >> 12) & 0xF
        kind = {8: "tlbi", 7: "dc/ic"}.get(crn, "sys")
        raise Unsupported("tlb_cache",
                          f"{kind}: ARM maintenance granularity and coherence "
                          f"rules differ from INVLPG/WBINVD")
    if w == 0xD69F03E0:
        raise Unsupported("exception_model",
                          "eret: returns from an exception level; x86 has rings "
                          "and IRET with different semantics")
    if (w & 0xFFE0001F) in (0xD4000001, 0xD4000002, 0xD4000003):
        raise Unsupported("exception_model",
                          "svc/hvc/smc: exception-level entry, not a call")

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
        return ("blraa" if link else "braa",
                [f"mov  rdi, {hostreg(rn)}",
                 "and  rdi, 0x0000ffffffffffff   ; strip PAC bits",
                 f"{op} [guest_dispatch + rdi*8]  ; indirect via translation map"])

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
        return "add", [f"mov  {hostreg(rd)}, {hostreg(rn)}",
                       f"add  {hostreg(rd)}, {imm:#x}"]
    if (w & 0x7F800000) == 0x51000000:      # SUB (immediate)
        rd, rn, imm = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0xFFF
        if (w >> 22) & 1:
            imm <<= 12
        if rd == rn:
            return "sub", [f"sub  {hostreg(rd)}, {imm:#x}"]
        return "sub", [f"mov  {hostreg(rd)}, {hostreg(rn)}",
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

    # ---- loads and stores -------------------------------------------------
    if (w & 0xFFC00000) == 0xF9400000:      # LDR (unsigned offset, 64-bit)
        rt, rn, imm = w & 0x1F, (w >> 5) & 0x1F, ((w >> 10) & 0xFFF) * 8
        return "ldr", [f"mov  {hostreg(rt)}, [{hostreg(rn)}+{imm:#x}]"]
    if (w & 0xFFC00000) == 0xF9000000:      # STR (unsigned offset, 64-bit)
        rt, rn, imm = w & 0x1F, (w >> 5) & 0x1F, ((w >> 10) & 0xFFF) * 8
        return "str", [f"mov  [{hostreg(rn)}+{imm:#x}], {hostreg(rt)}"]
    if (w & 0xFFC00000) == 0xA9800000 or (w & 0xFFC00000) == 0xA9000000:
        rt, rn, rt2 = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0x1F
        imm = sextract(w, 15, 7) * 8
        return "stp", [f"mov  [{hostreg(rn)}+{imm:#x}], {hostreg(rt)}",
                       f"mov  [{hostreg(rn)}+{imm + 8:#x}], {hostreg(rt2)}"]
    if (w & 0xFFC00000) == 0xA9400000 or (w & 0xFFC00000) == 0xA8C00000:
        rt, rn, rt2 = w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0x1F
        imm = sextract(w, 15, 7) * 8
        return "ldp", [f"mov  {hostreg(rt)}, [{hostreg(rn)}+{imm:#x}]",
                       f"mov  {hostreg(rt2)}, [{hostreg(rn)}+{imm + 8:#x}]"]

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
