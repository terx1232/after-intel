#!/usr/bin/env python3
"""
loadmap.py -- derive the memory layout a bootloader must construct for an
arm64e kernel collection.

This is step one of IbootCore. Before anything can hand control to XNU, it has
to know where the kernel wants to live: which segments exist, what virtual
addresses they claim, where the entry point is, and how much contiguous space
the whole collection occupies.

All of that is declared by the kernel itself in its Mach-O load commands. This
reads them and prints the map, plus the derived values that go straight into
`boot_args` - `virtBase`, `physBase` and `topOfKernelData`.

Input is a decompressed kernel collection (an `MH_FILESET`), i.e. the output of
`tools/im4p_extract.py`.

Usage:
    python loadmap.py <kernel> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_UNIXTHREAD = 0x5
LC_FILESET_ENTRY = 0x80000035
LC_UUID = 0x1B

VM_PROT = {1: "r", 2: "w", 4: "x"}


def prot_str(p: int) -> str:
    return "".join(VM_PROT[b] if p & b else "-" for b in (1, 2, 4))


def parse(path: str) -> dict:
    b = open(path, "rb").read()
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = \
        struct.unpack_from("<IiiIIII", b, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"not a 64-bit little-endian Mach-O ({magic:#x})")

    out = {
        "file": os.path.abspath(path),
        "file_size": len(b),
        "cputype": cputype,
        "cpusubtype": cpusubtype,
        "filetype": filetype,
        "ncmds": ncmds,
        "segments": [],
        "fileset_entries": [],
        "uuid": None,
        "entry": None,
    }

    off = 32
    for _ in range(ncmds):
        if off + 8 > len(b):
            break
        cmd, cmdsize = struct.unpack_from("<II", b, off)
        if cmdsize == 0:
            break

        if cmd == LC_SEGMENT_64:
            name = b[off + 8:off + 24].split(b"\x00")[0].decode("ascii", "replace")
            (vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects,
             segflags) = struct.unpack_from("<QQQQiiII", b, off + 24)
            out["segments"].append({
                "name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                "fileoff": fileoff, "filesize": filesize,
                "initprot": initprot, "maxprot": maxprot,
                "prot": prot_str(initprot), "nsects": nsects,
            })

        elif cmd == LC_FILESET_ENTRY:
            vmaddr, fileoff, entry_id_off = struct.unpack_from("<QQI", b, off + 8)
            s = b[off + entry_id_off:off + cmdsize].split(b"\x00")[0]
            out["fileset_entries"].append({
                "id": s.decode("utf-8", "replace"),
                "vmaddr": vmaddr, "fileoff": fileoff,
            })

        elif cmd == LC_UUID:
            u = b[off + 8:off + 24]
            out["uuid"] = "-".join((u[:4].hex(), u[4:6].hex(), u[6:8].hex(),
                                    u[8:10].hex(), u[10:].hex()))

        elif cmd == LC_UNIXTHREAD:
            # ARM_THREAD_STATE64 is x[29], fp, lr, sp, pc -- pc is index 32.
            state_off = off + 16
            pc_off = state_off + 32 * 8
            if pc_off + 8 <= len(b):
                (pc,) = struct.unpack_from("<Q", b, pc_off)
                out["entry"] = pc

        off += cmdsize

    segs = [s for s in out["segments"] if s["vmsize"]]
    if segs:
        lo = min(s["vmaddr"] for s in segs)
        hi = max(s["vmaddr"] + s["vmsize"] for s in segs)
        out["vm_low"] = lo
        out["vm_high"] = hi
        out["vm_span"] = hi - lo
    return out


def report(m: dict, out=sys.stdout) -> None:
    print(f"\n=== kernel load map: {os.path.basename(m['file'])} ===\n", file=out)
    print(f"file size       : {m['file_size']:,} bytes", file=out)
    arch = "arm64e" if m["cputype"] == 0x0100000C else str(m["cputype"])
    print(f"cputype/subtype : {m['cputype']:#x} / "
          f"{m['cpusubtype'] & 0xffffffff:#x}  ({arch})", file=out)
    print(f"filetype        : {m['filetype']} "
          f"({'MH_FILESET' if m['filetype'] == 12 else '?'})", file=out)
    print(f"UUID            : {m['uuid']}", file=out)
    print(f"kexts in fileset: {len(m['fileset_entries'])}", file=out)
    if m.get("entry") is not None:
        print(f"entry point (pc): {m['entry']:#018x}", file=out)

    print(f"\n{'segment':<20}{'vmaddr':>20}{'vmsize':>14}{'fileoff':>12}"
          f"{'filesize':>12}  prot", file=out)
    print("-" * 82, file=out)
    for s in m["segments"]:
        print(f"{s['name']:<20}{s['vmaddr']:>#20x}{s['vmsize']:>14,}"
              f"{s['fileoff']:>12,}{s['filesize']:>12,}  {s['prot']}", file=out)

    if "vm_low" in m:
        print(f"\nvirtual span    : {m['vm_low']:#018x} .. {m['vm_high']:#018x}",
              file=out)
        print(f"                  {m['vm_span']:,} bytes "
              f"({m['vm_span'] / 2**20:.1f} MiB)", file=out)
        if m["vm_span"] == m["file_size"]:
            print("                  equals the file size: the collection maps",
                  file=out)
            print("                  1:1, so vmaddr = virtBase + fileoff",
                  file=out)

        print("\nderived boot_args values a loader must supply:", file=out)
        print(f"  virtBase        = {m['vm_low']:#018x}", file=out)
        print("  physBase        = <where the loader places the image>", file=out)
        print(f"  topOfKernelData = physBase + {m['vm_span']:#x} "
              f"(plus device tree and boot_args)", file=out)
        print("  memSize         = <emulated RAM size>", file=out)

    print("\nNOTE: this is the layout the kernel declares. It says nothing about",
          file=out)
    print("      whether the machine state, device tree or signature checks are",
          file=out)
    print("      satisfied - only where the image expects to be.", file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kernel")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    m = parse(args.kernel)
    report(m)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
