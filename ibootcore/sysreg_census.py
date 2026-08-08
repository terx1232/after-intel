#!/usr/bin/env python3
"""
sysreg_census.py -- decode every MSR/MRS in a kernel and name the system
registers it touches.

"Untranslatable" is the wrong word for these. An MRS is a read and an MSR is a
write; against a shadow register file held in memory they are ordinary loads
and stores. What makes a handful of them hard is side effects: writing TTBR0_EL1
changes the address space, writing SCTLR_EL1 turns the MMU on, writing VBAR_EL1
moves the exception vectors. Those need a callback into a runtime, the rest do
not.

So the useful question is not how many there are but which registers they are,
and this answers it.

Encoding, from the Arm ARM:

    MRS Xt, <sysreg>    1101 0101 0011 o0 op1 CRn CRm op2 Rt
    MSR <sysreg>, Xt    1101 0101 0001 o0 op1 CRn CRm op2 Rt

with the register identified by the tuple (op0, op1, CRn, CRm, op2), where
op0 = 2 + the o0 bit.

Usage:
    python sysreg_census.py <kernel> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter

# (op0, op1, CRn, CRm, op2) -> name. The ones a kernel touches during boot,
# plus everything seen in practice; anything unlisted is reported by its tuple.
SYSREGS = {
    (3, 0, 0, 0, 0): "MIDR_EL1",
    (3, 0, 0, 0, 5): "MPIDR_EL1",
    (3, 0, 0, 0, 6): "REVIDR_EL1",
    (3, 0, 0, 4, 0): "ID_AA64PFR0_EL1",
    (3, 0, 0, 4, 1): "ID_AA64PFR1_EL1",
    (3, 0, 0, 5, 0): "ID_AA64DFR0_EL1",
    (3, 0, 0, 6, 0): "ID_AA64ISAR0_EL1",
    (3, 0, 0, 6, 1): "ID_AA64ISAR1_EL1",
    (3, 0, 0, 7, 0): "ID_AA64MMFR0_EL1",
    (3, 0, 0, 7, 1): "ID_AA64MMFR1_EL1",
    (3, 0, 0, 7, 2): "ID_AA64MMFR2_EL1",
    (3, 0, 1, 0, 0): "SCTLR_EL1",
    (3, 0, 1, 0, 1): "ACTLR_EL1",
    (3, 0, 1, 0, 2): "CPACR_EL1",
    (3, 0, 2, 0, 0): "TTBR0_EL1",
    (3, 0, 2, 0, 1): "TTBR1_EL1",
    (3, 0, 2, 0, 2): "TCR_EL1",
    (3, 0, 4, 0, 0): "SPSR_EL1",
    (3, 0, 4, 0, 1): "ELR_EL1",
    (3, 0, 4, 1, 0): "SP_EL0",
    (3, 0, 4, 2, 0): "SPSel",
    (3, 0, 4, 2, 2): "CurrentEL",
    (3, 0, 4, 2, 3): "PAN",
    (3, 0, 5, 1, 0): "AFSR0_EL1",
    (3, 0, 5, 1, 1): "AFSR1_EL1",
    (3, 0, 5, 2, 0): "ESR_EL1",
    (3, 0, 6, 0, 0): "FAR_EL1",
    (3, 0, 7, 4, 0): "PAR_EL1",
    (3, 0, 10, 2, 0): "MAIR_EL1",
    (3, 0, 10, 3, 0): "AMAIR_EL1",
    (3, 0, 12, 0, 0): "VBAR_EL1",
    (3, 0, 13, 0, 1): "CONTEXTIDR_EL1",
    (3, 0, 13, 0, 4): "TPIDR_EL1",
    (3, 3, 13, 0, 2): "TPIDR_EL0",
    (3, 3, 13, 0, 3): "TPIDRRO_EL0",
    (3, 3, 4, 2, 0): "NZCV",
    (3, 3, 4, 2, 1): "DAIF",
    (3, 3, 4, 4, 0): "FPCR",
    (3, 3, 4, 4, 1): "FPSR",
    (3, 3, 14, 0, 0): "CNTFRQ_EL0",
    (3, 3, 14, 0, 1): "CNTPCT_EL0",
    (3, 3, 14, 0, 2): "CNTVCT_EL0",
    (3, 0, 14, 1, 0): "CNTKCTL_EL1",
    (3, 0, 12, 1, 0): "ISR_EL1",
    (3, 1, 0, 0, 1): "CLIDR_EL1",
    (3, 1, 0, 0, 0): "CCSIDR_EL1",
    (3, 2, 0, 0, 0): "CSSELR_EL1",
    (3, 3, 0, 0, 1): "CTR_EL0",
    (3, 3, 0, 0, 7): "DCZID_EL0",
    (3, 0, 1, 2, 0): "ZCR_EL1",
    (3, 4, 1, 0, 0): "SCTLR_EL2",
    (3, 6, 1, 0, 0): "SCTLR_EL3",
    # PAC keys -- their presence tells you the kernel manages authentication
    (3, 0, 2, 1, 0): "APIAKeyLo_EL1",
    (3, 0, 2, 1, 1): "APIAKeyHi_EL1",
    (3, 0, 2, 1, 2): "APIBKeyLo_EL1",
    (3, 0, 2, 1, 3): "APIBKeyHi_EL1",
    (3, 0, 2, 2, 0): "APDAKeyLo_EL1",
    (3, 0, 2, 2, 1): "APDAKeyHi_EL1",
    (3, 0, 2, 2, 2): "APDBKeyLo_EL1",
    (3, 0, 2, 2, 3): "APDBKeyHi_EL1",
    (3, 0, 2, 3, 0): "APGAKeyLo_EL1",
    (3, 0, 2, 3, 1): "APGAKeyHi_EL1",
}

# Writes to these change how the machine addresses or dispatches, so a
# translation has to do more than store the value.
SIDE_EFFECTS = {
    "TTBR0_EL1": "address space root -- shadow page tables must be rebuilt",
    "TTBR1_EL1": "kernel address space root -- same",
    "TCR_EL1": "translation control: granule and address size",
    "SCTLR_EL1": "MMU and cache enable",
    "VBAR_EL1": "exception vector base -- x86 IDT must follow it",
    "MAIR_EL1": "memory attribute encodings",
    "CPACR_EL1": "FP/SIMD trapping",
    "SPSel": "which stack pointer is in use",
    "DAIF": "interrupt masking -- maps to cli/sti",
    "SP_EL0": "the other stack pointer",
    "ELR_EL1": "exception return address",
    "SPSR_EL1": "saved processor state",
}


def decode(w: int):
    """Return (kind, op0, op1, crn, crm, op2, rt) or None."""
    if (w & 0xFFF00000) == 0xD5300000:
        kind = "mrs"
    elif (w & 0xFFF00000) == 0xD5100000:
        kind = "msr"
    else:
        return None
    o0 = (w >> 19) & 1
    op0 = 2 + o0
    op1 = (w >> 16) & 7
    crn = (w >> 12) & 0xF
    crm = (w >> 8) & 0xF
    op2 = (w >> 5) & 7
    rt = w & 0x1F
    return kind, op0, op1, crn, crm, op2, rt


def exec_segments(path: str):
    b = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", b, 16)[0]
    off = 32
    out = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break
        if cmd == 0x19:
            vmaddr, vmsize, fileoff, filesize, maxprot, initprot = \
                struct.unpack_from("<QQQQii", b, off + 24)
            if initprot & 4:
                out.append((vmaddr, fileoff, filesize))
        off += cmdsize
    return b, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    b, segs = exec_segments(args.kernel)
    reads, writes = Counter(), Counter()
    unknown = Counter()

    for vmaddr, fileoff, filesize in segs:
        for i in range(filesize // 4):
            (w,) = struct.unpack_from("<I", b, fileoff + i * 4)
            got = decode(w)
            if not got:
                continue
            kind, op0, op1, crn, crm, op2, _rt = got
            key = (op0, op1, crn, crm, op2)
            name = SYSREGS.get(key)
            if name is None:
                name = f"S{op0}_{op1}_C{crn}_C{crm}_{op2}"
                unknown[name] += 1
            (reads if kind == "mrs" else writes)[name] += 1

    total = sum(reads.values()) + sum(writes.values())
    print(f"\n=== system register census: {os.path.basename(args.kernel)} ===\n")
    print(f"total MSR/MRS      : {total:,}")
    print(f"  reads  (mrs)     : {sum(reads.values()):,}")
    print(f"  writes (msr)     : {sum(writes.values()):,}")
    print(f"distinct registers : {len(set(reads) | set(writes))}")
    print(f"  unnamed here     : {len(unknown)} "
          f"({sum(unknown.values()):,} accesses)")

    print(f"\n{'register':<22}{'reads':>9}{'writes':>9}  note")
    print("-" * 76)
    allregs = sorted(set(reads) | set(writes),
                     key=lambda r: -(reads[r] + writes[r]))
    for r in allregs[:28]:
        note = ""
        if writes[r] and r in SIDE_EFFECTS:
            note = "WRITE HAS SIDE EFFECTS: " + SIDE_EFFECTS[r]
        print(f"{r:<22}{reads[r]:>9,}{writes[r]:>9,}  {note[:44]}")

    hard = sum(writes[r] for r in writes if r in SIDE_EFFECTS)
    easy = total - hard
    print(f"\nsplit by what a translation actually has to do:")
    print(f"  plain shadow-file load or store : {easy:,} ({100.0*easy/total:.2f}%)")
    print(f"  needs a runtime callback        : {hard:,} ({100.0*hard/total:.2f}%)")

    if args.json:
        json.dump({"reads": dict(reads.most_common()),
                   "writes": dict(writes.most_common()),
                   "total": total, "callback_writes": hard},
                  open(args.json, "w", encoding="utf-8"), indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
