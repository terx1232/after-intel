#!/usr/bin/env python3
"""
translatability.py -- count the instructions in an arm64e kernel that have no
x86-64 equivalent, and classify why.

"Translate the kernel to x86" is a reasonable-sounding request and it deserves
a measured answer rather than an assertion. Most arm64 instructions translate
mechanically: an add is an add, a load is a load, a branch is a branch. What
does not translate is the subset that expresses *architecture semantics* rather
than computation:

  pointer authentication  arm64e signs pointers in the code stream. x86-64 has
                          no equivalent, and a signed branch target is not
                          statically resolvable, so these cannot simply be
                          dropped either.

  system registers        MSR/MRS reach TTBR, SCTLR, VBAR, TCR and the rest.
                          x86 has CR0/CR3/CR4 and MSRs, but the page table
                          format, translation control and exception vectoring
                          they configure are different machines, not different
                          spellings.

  exception model         ERET returns from an exception level. x86 has no
                          exception levels; it has rings, an IDT and IRET with
                          different semantics.

  TLB and cache ops       TLBI and DC/IC by set/way and by VA have no direct
                          counterpart; x86 has INVLPG and WBINVD with different
                          granularity and coherence rules.

  barriers                DSB/DMB/ISB are the weak memory model made explicit.
                          On x86 most become no-ops, which is the one category
                          where the translation direction is favourable.

Counting these gives the size of the problem in instructions, which is a
better basis for a decision than an adjective.

Usage:
    python translatability.py <kernel> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter

LC_SEGMENT_64 = 0x19


def classify(w: int):
    """Return (category, mnemonic) for instructions with no x86 equivalent."""

    # -- pointer authentication -------------------------------------------
    # Hint-space PAC ops: PACIASP, PACIBSP, AUTIASP, AUTIBSP, XPACLRI ...
    if (w & 0xFFFFF01F) == 0xD503201F:
        crm_op2 = (w >> 5) & 0x7F
        if crm_op2 in (0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
                       0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F):
            return "pointer_auth", "pac/aut (hint form)"
    # Register form: PACIA/PACIB/PACDA/PACDB/AUTIA/... (dp-1source)
    if (w & 0xFFFE0000) == 0xDAC10000:
        return "pointer_auth", "pac/aut (register form)"
    # RETAA / RETAB
    if w in (0xD65F0BFF, 0xD65F0FFF):
        return "pointer_auth", "retaa/retab"
    # BRAA/BRAB/BLRAA/BLRAB and the Z variants
    if (w & 0xFE1FF800) == 0xD61F0800:
        return "pointer_auth", "braa/blraa"

    # -- exception model ---------------------------------------------------
    if w == 0xD69F03E0:
        return "exception_model", "eret"
    if (w & 0xFFE0001F) == 0xD4000001:
        return "exception_model", "svc"
    if (w & 0xFFE0001F) == 0xD4000002:
        return "exception_model", "hvc"
    if (w & 0xFFE0001F) == 0xD4000003:
        return "exception_model", "smc"

    # -- barriers ----------------------------------------------------------
    if (w & 0xFFFFF0FF) == 0xD503309F:
        return "barrier", "dsb"
    if (w & 0xFFFFF0FF) == 0xD50330BF:
        return "barrier", "dmb"
    if (w & 0xFFFFF0FF) == 0xD50330DF:
        return "barrier", "isb"

    # -- TLB and cache maintenance (SYS/SYSL with op1 in the maintenance
    #    space) -- these decode as MSR-immediate-adjacent encodings
    if (w & 0xFFF80000) == 0xD5080000:
        crn = (w >> 12) & 0xF
        if crn == 8:
            return "tlb_cache", "tlbi"
        if crn == 7:
            return "tlb_cache", "dc/ic"
        return "tlb_cache", "sys"

    # -- system register access -------------------------------------------
    if (w & 0xFFF00000) == 0xD5100000:
        return "system_register", "msr"
    if (w & 0xFFF00000) == 0xD5300000:
        return "system_register", "mrs"

    return None, None


def exec_sections(path: str):
    """Yield (segname, fileoff, size) for executable segments."""
    b = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", b, 16)[0]
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == LC_SEGMENT_64:
            name = b[off + 8:off + 24].split(b"\x00")[0].decode("ascii", "replace")
            vmaddr, vmsize, fileoff, filesize, maxprot, initprot = \
                struct.unpack_from("<QQQQii", b, off + 24)
            if initprot & 4:      # VM_PROT_EXECUTE
                yield name, fileoff, filesize
        off += cmdsize


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    b = open(args.kernel, "rb").read()
    cats = Counter()
    mnemonics = Counter()
    total_words = 0
    segs = []

    for name, fileoff, filesize in exec_sections(args.kernel):
        n = filesize // 4
        segs.append({"segment": name, "bytes": filesize, "words": n})
        total_words += n
        for i in range(fileoff, fileoff + (n * 4), 4):
            (w,) = struct.unpack_from("<I", b, i)
            cat, mn = classify(w)
            if cat:
                cats[cat] += 1
                mnemonics[mn] += 1

    untranslatable = sum(cats.values())

    print(f"\n=== translatability: {os.path.basename(args.kernel)} ===\n")
    for s in segs:
        print(f"executable segment {s['segment']:<14}"
              f"{s['bytes']:>12,} bytes  {s['words']:>11,} instructions")
    print(f"{'total':<32}{'':>12}  {total_words:>11,} instructions\n")

    print(f"{'category':<20}{'count':>10}{'share':>9}  what x86 lacks")
    print("-" * 78)
    notes = {
        "pointer_auth":   "no equivalent; signed targets not statically known",
        "system_register": "different MMU, TCR and vector model entirely",
        "exception_model": "rings and IDT, not exception levels",
        "tlb_cache":       "different granularity and coherence rules",
        "barrier":         "mostly no-ops on x86 - the favourable direction",
    }
    for c, n in cats.most_common():
        print(f"{c:<20}{n:>10}{100.0 * n / total_words:>8.3f}%  {notes.get(c,'')}")
    print("-" * 78)
    print(f"{'untranslatable':<20}{untranslatable:>10}"
          f"{100.0 * untranslatable / total_words:>8.3f}%")

    print("\nby mnemonic:")
    for m, n in mnemonics.most_common():
        print(f"    {m:<24}{n:>10,}")

    hard = untranslatable - cats.get("barrier", 0)
    print(f"\nBarriers aside - they mostly vanish on a strongly ordered host -")
    print(f"that leaves {hard:,} instructions that encode ARM's machine model")
    print(f"rather than a computation. Each one needs a semantic decision, not")
    print(f"a substitution: what x86 construct means the same thing here, and")
    print(f"what has to change around it for that to remain true.")
    print(f"\nAnd this counts the kernel only. It is under 5% of the system.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"kernel": os.path.basename(args.kernel),
                       "segments": segs,
                       "total_instructions": total_words,
                       "categories": dict(cats),
                       "mnemonics": dict(mnemonics),
                       "untranslatable": untranslatable}, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
