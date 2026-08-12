#!/usr/bin/env python3
"""
gpt.py -- read the GUID partition table of a disk image.

The decrypted BaseSystem is a whole disk, not a bare filesystem: a protective
MBR, a GPT at LBA 1, and an APFS container inside one of the partitions. The
ramdisk path needs to know where that container starts, and whether the image is
intact all the way to the backup table, before it is worth booting.

Usage:
    python gpt.py BaseSystem.dmg
"""

from __future__ import annotations

import argparse
import struct
import sys
import uuid

APFS_TYPE = uuid.UUID("7C3457EF-0000-11AA-AA11-00306543ECAC")
KNOWN = {
    APFS_TYPE: "Apple APFS",
    uuid.UUID("48465300-0000-11AA-AA11-00306543ECAC"): "Apple HFS+",
    uuid.UUID("C12A7328-F81F-11D2-BA4B-00A0C93EC93B"): "EFI System",
    uuid.UUID("426F6F74-0000-11AA-AA11-00306543ECAC"): "Apple Boot",
}


def guid(raw: bytes) -> uuid.UUID:
    return uuid.UUID(bytes_le=raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--sector", type=int, default=512)
    args = ap.parse_args(argv)

    fh = open(args.image, "rb")
    fh.seek(args.sector)
    hdr = fh.read(92)
    if hdr[:8] != b"EFI PART":
        print(f"  no GPT at LBA 1 (found {hdr[:8]!r})")
        return 1

    (_, rev, hdr_size, _, _, current_lba, backup_lba, first_usable,
     last_usable) = struct.unpack_from("<8sIIIIQQQQ", hdr, 0)
    disk = guid(hdr[56:72])
    (entries_lba, n_entries, entry_size) = struct.unpack_from("<QII", hdr, 72)

    print(f"\n  GPT revision {rev >> 16}.{rev & 0xFFFF}, header {hdr_size} bytes")
    print(f"  disk GUID      {disk}")
    print(f"  this header    LBA {current_lba}   backup LBA {backup_lba}")
    print(f"  usable         LBA {first_usable} .. {last_usable}")
    print(f"  entries        {n_entries} x {entry_size} bytes at LBA {entries_lba}\n")

    fh.seek(entries_lba * args.sector)
    table = fh.read(n_entries * entry_size)
    for i in range(n_entries):
        e = table[i * entry_size:(i + 1) * entry_size]
        type_guid = guid(e[:16])
        if int(type_guid) == 0:
            continue
        first, last = struct.unpack_from("<QQ", e, 32)
        name = e[56:128].decode("utf-16-le").rstrip("\x00")
        kind = KNOWN.get(type_guid, str(type_guid))
        size = (last - first + 1) * args.sector
        print(f"  partition {i}: {name!r}")
        print(f"      type    {kind}")
        print(f"      LBA     {first} .. {last}")
        print(f"      offset  {first * args.sector:#x}  size {size:,} bytes")
        fh.seek(first * args.sector)
        probe = fh.read(64)
        if probe[32:36] == b"NXSB":
            bs, blocks = struct.unpack_from("<IQ", probe, 36)
            print(f"      APFS    block size {bs}, {blocks:,} blocks "
                  f"({bs * blocks:,} bytes)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
