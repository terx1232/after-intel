#!/usr/bin/env python3
"""
guest.py -- walk the running kernel's processes and threads through the monitor.

Every offset here was taken from the kernel's own code or verified against it,
not guessed, because guessing produced two confident wrong answers earlier in
this work.

    proc -> task            +0x7c0    kernel_task minus kernproc, and it holds
                                      across boots; the task is allocated
                                      immediately after the proc
    task -> threads queue   +0x50     the kernel task has next != prev, launchd
                                      has next == prev, and both point back to
                                      task+0x50, which is what a queue head does
    thread link             +0x00     so the thread is the link address itself
    thread -> thread_ro     +0x3f0    from current_task: it reads tpidr_el1 and
                                      tail-calls a routine doing
                                        ldr x1, [x0, #0x3f0]
                                        ...range checks...
                                        ldr x0, [x1, #0x28]
    thread_ro -> task       +0x28     the second load above; ro+0 points back at
                                      the thread, which makes the pair checkable
    thread -> state         +0x1c8    thread_block_reason masks this field with
                                      0x97, which is exactly
                                      WAIT|SUSP|RUN|UNINT|IDLE
    proc -> p_pid           +0x60     0 for the kernel, 1 for launchd
    proc -> p_name          +0x5cd    p_comm sits at +0x5bc before it

The globals kernproc and kernel_task come from symbols.py.

Usage, against a guest with `-monitor tcp:127.0.0.1:PORT,server,nowait`:
    python guest.py --port 56000 --kernel vma2-capfix.kernel
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import symbols

STATE_FLAGS = [(0x01, "WAIT"), (0x02, "SUSP"), (0x04, "RUN"), (0x08, "UNINT"),
               (0x10, "TERMINATE"), (0x20, "TERMINATE2"), (0x40, "WAIT_REPORT"),
               (0x80, "IDLE")]

PROC_TASK = 0x7C0
TASK_THREADS = 0x50
THREAD_RO = 0x3F0
RO_TASK = 0x28
THREAD_STATE = 0x1C8
PROC_PID = 0x60
PROC_NAME = 0x5CD
PROC_NEXT = 0x08


class Monitor:
    """The QEMU monitor, used only to read guest memory."""

    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(6)
        time.sleep(0.3)
        self._drain()

    def _drain(self):
        try:
            while True:
                if not self.sock.recv(65536):
                    break
        except OSError:
            pass

    def command(self, text: str, settle: float = 1.0):
        self.sock.sendall((text + "\n").encode())
        time.sleep(settle)
        self._drain()

    def read(self, addr: int, size: int) -> bytes:
        path = os.path.join(tempfile.gettempdir(), f"guest_{addr:x}.bin")
        self.command(f"memsave {addr:#x} {size} {path}", 0.6 + size / 400000)
        with open(path, "rb") as fh:
            data = fh.read()
        os.unlink(path)
        return data

    def u64(self, addr: int) -> int:
        return struct.unpack_from("<Q", self.read(addr, 8), 0)[0]


def state_names(value: int) -> str:
    names = [n for bit, n in STATE_FLAGS if value & bit]
    return " | ".join(names) if names else "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args(argv)

    _, by_name, _ = symbols.collect(args.kernel)
    if "kernproc" not in by_name:
        print("  kernproc: no such symbol")
        return 1

    mon = Monitor(args.port)
    proc = mon.u64(by_name["kernproc"])
    print()
    for _ in range(args.limit):
        if not proc:
            break
        blob = mon.read(proc, 0x800)
        if len(blob) < 0x600:
            break
        pid, = struct.unpack_from("<I", blob, PROC_PID)
        name = blob[PROC_NAME:PROC_NAME + 0x20].split(b"\x00")[0].decode("latin1")
        if not name:
            break
        task = proc + PROC_TASK
        head = mon.u64(task + TASK_THREADS)
        print(f"  pid {pid:<5} {name:<20} task {task:#x}")

        thread, seen = head, 0
        while thread and thread != task + TASK_THREADS and seen < 16:
            ro = mon.u64(thread + THREAD_RO)
            owner = mon.u64(ro) if ro else 0
            state, = struct.unpack_from("<I", mon.read(thread + THREAD_STATE, 4), 0)
            ok = owner == thread
            print(f"      thread {thread:#x}  state {state:#06x} "
                  f"({state_names(state)}){'' if ok else '  [ro mismatch]'}")
            thread = mon.u64(thread)
            seen += 1

        proc, = struct.unpack_from("<Q", blob, PROC_NEXT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
