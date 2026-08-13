#!/usr/bin/env python3
"""
trace_wait.py -- record what the last thread to block was waiting on.

launchd stops after dyld's ignition prints its arguments, and ten samples of the
program counter land in the scheduler every time and in EL0 never, so it is
blocked rather than looping. Which is a complete diagnosis of the symptom and
none of the cause: a blocked thread is waiting on an event, and nothing printed
says which.

The obvious instrument - make assert_wait printf its argument - is the wrong one
here. printf takes locks, locks call assert_wait, and the recursion would be the
only thing the log ever showed. So this writes instead of printing: five
instructions in a code cave that stash the wait event and the return address in
a scratch page and then continue. No stack, no calls, nothing that can re-enter.

Afterwards the values are read out of guest memory through the QEMU monitor and
resolved with symbols.py, which turns "blocked somewhere" into a name.

    python trace_wait.py <kernel> --out <patched>
    python trace_wait.py <kernel> --out <patched> --func thread_block
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadmap
import symbols

KV_HIGH = 0xFFFFFE0000000000


def find_run(data: bytes, lo: int, hi: int, length: int, value: int = 0):
    """The first offset of a run of `length` bytes equal to `value`."""
    needle = bytes([value]) * length
    i = data.find(needle, lo, hi)
    return i if i >= 0 else None


def seg(m: dict, name: str):
    return next(s for s in m["segments"] if s["name"] == name)


# Entries, each 16 bytes, after an 8-byte index. A short ring is useless here:
# idle workloops block every few milliseconds, so 64 slots are overwritten long
# before the guest can be inspected, and all that survives is the idling. The
# mask below must stay in step with this.
RING = 32768                       # entries are 32 bytes now, so half as many
RING_LIMIT_WORD = 0xF140411F       # cmp x8, #16, lsl #12   (= RING)
RING_SKIP_WORD = 0x54000082        # b.hs +4 instructions
# One-shot keeps the first RING blocks, which is right when the interesting wait
# is early. Wrapping keeps the last RING, which is right when it is late - and
# the wait that never returns is by definition the last thing that happened.
WRAP = True


def emit(cave_va: int, scratch_va: int, orig_word: int, resume_va: int):
    """Append (event, caller) to a ring, then run the displaced instruction.

    A single slot only ever shows the last thread to block, which on an idle
    machine is an IOWorkLoop going back to sleep - true and useless. A ring keeps
    the history, so the one wait that never ends is in it alongside the ones that
    do.

    x8 and x9 are temporaries and assert_wait returns an int, so neither needs
    saving; that is what keeps this to plain loads and stores with no stack and
    no calls.
    """
    words = []

    page_delta = (scratch_va & ~0xFFF) - (cave_va & ~0xFFF)
    imm = page_delta >> 12
    immlo, immhi = imm & 3, (imm >> 2) & 0x7FFFF
    words.append(0x90000000 | (immlo << 29) | (immhi << 5) | 9)   # adrp x9, page

    off = scratch_va & 0xFFF
    words.append(0x91000000 | (off << 10) | (9 << 5) | 9)          # add x9, x9, #off
    words.append(0xF9400128)                                       # ldr x8, [x9]
    words.append(0x91000508)                                       # add x8, x8, #1
    words.append(0xF9000128)                                       # str x8, [x9]
    if WRAP:
        words.append(0x92403908)                                   # and x8, x8, #0x7fff
        words.append(0xD503201F)                                   # nop
    else:
        words.append(RING_LIMIT_WORD)                              # cmp x8, #RING
        words.append(RING_SKIP_WORD)                               # b.hs past the stores
    # The wait event says little; the thread says everything. A thread that
    # blocks and is never woken appears once and never again, while every
    # working thread keeps reappearing, so recording tpidr_el1 turns "which of
    # these 47 sites never returns" into a question the data answers by itself.
    words.append(0xD538D08A)                                       # mrs x10, tpidr_el1
    # elr_el1 still holds the userland return address for a thread that entered
    # through svc and has taken no nested exception since, so a value up in the
    # shared cache marks the one thread that came from EL0 - which is the whole
    # question here, since every other blocker is a kernel worker.
    # x0 rather than elr_el1: elr never carries a userland address by the time a
    # thread blocks, while the first argument is what identifies the call - for
    # sysctl_handle_string it is the oid, and symbols name those outright.
    words.append(0xAA0003EB)                                       # mov x11, x0
    words.append(0x8B081529)                                       # add x9, x9, x8, lsl #5
    words.append(0xF9001129)                                       # str x9, [x9, #32] placeholder
    words[-1] = 0xF900112A                                         # str x10, [x9, #32]
    words.append(0xF900152B)                                       # str x11, [x9, #40]
    words.append(0xF900193E)                                       # str x30, [x9, #48]

    words.append(orig_word)

    delta = resume_va - (cave_va + 4 * len(words))
    words.append(0x14000000 | ((delta // 4) & 0x3FFFFFF))
    return words


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--out", required=True)
    ap.add_argument("--func", default="assert_wait")
    ap.add_argument("--at",
                    help="instrument this address instead of a named function. "
                         "thread_block is three instructions that tail-call "
                         "thread_block_reason, which has no symbol, and every "
                         "caller that goes straight to the latter is invisible "
                         "from the former.")
    ap.add_argument("--scratch",
                    help="virtual address to write the ring to. Use the address "
                         "build_image --reserve prints: a zero run inside __DATA "
                         "looks free and is not - it is BSS, and writing there "
                         "panics the kernel with an os_refcnt overflow whose "
                         "counter address lands inside the ring.")
    args = ap.parse_args(argv)

    m = loadmap.parse(args.kernel)
    vb = m["vm_low"]
    data = bytearray(open(args.kernel, "rb").read())
    _, by_name, _ = symbols.collect(args.kernel)

    if args.at:
        target = int(args.at, 0)
        if target < 0xFFFFFFFF:
            target |= KV_HIGH
    elif args.func not in by_name:
        print(f"  {args.func}: no such symbol")
        return 1
    else:
        target = by_name[args.func]

    text = seg(m, "__TEXT_EXEC")
    cave_off = find_run(bytes(data), text["fileoff"],
                        text["fileoff"] + text["filesize"], 64)
    if cave_off is None:
        print("  no code cave in __TEXT_EXEC")
        return 1
    cave_va = vb + cave_off

    if args.scratch:
        scratch_va = int(args.scratch, 0)
        scratch_off = None
    else:
        dseg = seg(m, "__DATA")
        scratch_off = find_run(bytes(data), dseg["fileoff"],
                               dseg["fileoff"] + dseg["filesize"], 16 + RING * 16)
        if scratch_off is None:
            print("  no scratch run in __DATA")
            return 1
        # A 64-bit store needs its offset to be a multiple of eight, and a run
        # of zeros starts wherever it starts.
        scratch_off = (scratch_off + 7) & ~7
        scratch_va = vb + scratch_off

    orig_word, = struct.unpack_from("<I", data, target - vb)
    words = emit(cave_va, scratch_va, orig_word, target + 4)

    for i, w in enumerate(words):
        struct.pack_into("<I", data, cave_off + i * 4, w)

    delta = cave_va - target
    struct.pack_into("<I", data, target - vb,
                     0x14000000 | ((delta // 4) & 0x3FFFFFF))

    open(args.out, "wb").write(bytes(data))

    def short(v):
        return f"0x{v - KV_HIGH:x}"

    print(f"\n  {args.func} at {short(target)}, first word {orig_word:#010x}")
    print(f"  cave    {short(cave_va)}  ({len(words)} instructions)")
    print(f"  scratch {scratch_va:#x}  ({RING} entries, "
          f"{16 + RING * 16:,} bytes)")
    if scratch_off is None:
        print(f"\n  reserved range - read it with the monitor once stuck:")
        print(f"    pmemsave <physical of {scratch_va:#x}> "
              f"{16 + RING * 16} ring.bin")
    else:
        print(f"\n  WARNING: this is a zero run inside __DATA, which is BSS. "
              f"Prefer build_image --reserve.")
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
