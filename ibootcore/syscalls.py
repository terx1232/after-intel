#!/usr/bin/env python3
"""
syscalls.py -- list the system calls a function can reach.

dyld is self-contained, so a call that blocks does not show up as an import with
a helpful name; it shows up as `svc #0x80` behind a stub. This walks a function's
call graph to a given depth, finds the stubs that issue an svc, and reads the
syscall number out of the `mov x16, #N` that precedes it.

Written for the ignition sequence in /usr/lib/dyld, which prints its arguments
and then stops with launchd blocked in the kernel and never scheduled again.
Knowing which calls that code can make narrows a blocked thread to a handful of
candidates without a debugger.

Usage:
    python syscalls.py dyld --at 0x7b654
    python syscalls.py dyld --at 0x7b654 --depth 3
"""

from __future__ import annotations

import argparse
import struct
import sys

# BSD syscalls worth naming; the rest print as numbers.
NAMES = {
    3: "read", 4: "write", 5: "open", 6: "close", 20: "getpid",
    33: "access", 46: "sigaction", 48: "sigprocmask", 33554432 + 4: "?",
    59: "execve", 73: "munmap", 74: "mprotect", 75: "madvise",
    92: "fcntl", 93: "select", 116: "gettimeofday", 153: "?",
    169: "csops", 194: "getrlimit", 197: "mmap", 199: "lseek",
    202: "sysctl", 216: "?", 234: "?", 253: "?", 266: "?",
    286: "?", 301: "psynch_mutexwait", 302: "psynch_mutexdrop",
    305: "psynch_cvwait", 327: "issetugid", 336: "proc_info",
    338: "stat64", 339: "fstat64", 340: "lstat64", 344: "getdirentries64",
    346: "statfs64", 347: "fstatfs64", 348: "getfsstat64",
    357: "getaudit_addr", 366: "bsdthread_create", 372: "thread_selfid",
    381: "csrctl", 396: "read_nocancel", 397: "write_nocancel",
    398: "open_nocancel", 399: "close_nocancel",
    424: "?", 439: "openat", 440: "openat_nocancel",
    500: "getentropy", 520: "terminate_with_payload",
}


def load(path: str) -> bytes:
    return open(path, "rb").read()


def bl_targets(data: bytes, start: int, limit: int = 4000):
    """Call targets reachable by falling through from `start`."""
    seen = []
    for i in range(start, min(start + limit * 4, len(data) - 4), 4):
        (w,) = struct.unpack_from("<I", data, i)
        if (w & 0xFC000000) == 0x94000000:
            imm = w & 0x3FFFFFF
            if imm & 0x2000000:
                imm -= 0x4000000
            t = i + imm * 4
            if 0 <= t < len(data) and t not in seen:
                seen.append(t)
        if w == 0xD65F0FFF or w == 0xD65F03C0:      # retab / ret
            break
    return seen


def syscall_of(data: bytes, func: int, window: int = 24):
    """The syscall number a stub issues, if it issues one."""
    num = None
    for k in range(window):
        off = func + k * 4
        if off + 4 > len(data):
            break
        (w,) = struct.unpack_from("<I", data, off)
        if (w & 0xFFE0001F) == 0xD2800010:          # mov x16, #imm
            num = (w >> 5) & 0xFFFF
        if w == 0xD4001001:                          # svc #0x80
            return num
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("binary")
    ap.add_argument("--at", required=True)
    ap.add_argument("--depth", type=int, default=2)
    args = ap.parse_args(argv)

    data = load(args.binary)
    frontier = [int(args.at, 0)]
    visited = set()
    found = {}

    for level in range(args.depth):
        nxt = []
        for f in frontier:
            if f in visited:
                continue
            visited.add(f)
            for t in bl_targets(data, f):
                n = syscall_of(data, t)
                if n is not None:
                    found.setdefault(n, []).append((f, t))
                else:
                    nxt.append(t)
        frontier = nxt

    print(f"\n  reachable from {args.at} within depth {args.depth}: "
          f"{len(visited)} functions, {len(found)} distinct syscalls\n")
    for n in sorted(found):
        where = found[n][0]
        print(f"    {n:>5}  {NAMES.get(n, ''):<20} stub {where[1]:#x} "
              f"called from {where[0]:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
