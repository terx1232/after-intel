#!/usr/bin/env python3
"""
apfs_seal.py -- clear the sealed-volume flag on an APFS volume superblock.

The decrypted Base System is a sealed volume that carries no snapshot. APFS will
not root from it: the mount asks for a named root snapshot, finds none, falls
through to the authenticated path and panics on a null payload.

    fs_lookup_root_snapshot_name:375: md0s1 failed to get root-snapshot-name from DT
    apfs_find_named_root_snapshot_xid:2153: failed to retrieve default root snapshot xid
    apfs_vfsop_mount:2914: failed to find named root snapshot: Need authenticator (81)
    panic: "The global payload bytes pointer is NULL" @apfs_vfsops.c:2921

Supplying /chosen/root-hash does not change it; that property feeds a different
path, the one that boots the Base System as a disk image. What gates the
snapshot requirement is APFS_INCOMPAT_SEALED_VOLUME (0x20) in the volume
superblock, and a broken seal is a state APFS already knows how to mount - it is
what happens on real hardware when a sealed volume is modified.

Every object in APFS starts with a Fletcher-64 checksum over the rest of the
block, so the flag cannot be changed without recomputing it. This verifies the
checksum of every block it is about to touch *before* touching it. If the
implementation here disagreed with Apple's, that check would fail on unmodified
data and nothing would be written.

Usage:
    python apfs_seal.py BaseSystem-apfs.img
    python apfs_seal.py BaseSystem-apfs.img --write
"""

from __future__ import annotations

import argparse
import struct
import sys

SEALED = 0x20
INCOMPAT_OFF = 0x38          # apfs_incompatible_features, u64
MAGIC_OFF = 32               # 'APSB'

FLAGS = {
    0x01: "case-insensitive",
    0x02: "dataless-snaps",
    0x04: "enc-rolled",
    0x08: "normalization-insensitive",
    0x10: "incomplete-restore",
    0x20: "sealed-volume",
}


def fletcher64(block: bytes) -> int:
    """APFS object checksum: over the block past its own 8-byte checksum."""
    body = block[8:]
    sum1 = sum2 = 0
    mod = 0xFFFFFFFF
    for (word,) in struct.iter_unpack("<I", body):
        sum1 = (sum1 + word) % mod
        sum2 = (sum2 + sum1) % mod
    c1 = mod - ((sum1 + sum2) % mod)
    c2 = mod - ((sum1 + c1) % mod)
    return (c2 << 32) | c1


def describe(flags: int) -> str:
    names = [n for bit, n in FLAGS.items() if flags & bit]
    return ", ".join(names) if names else "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--write", action="store_true",
                    help="actually clear the flag; without it, report only")
    args = ap.parse_args(argv)

    fh = open(args.image, "r+b" if args.write else "rb")
    head = fh.read(64)
    if head[32:36] != b"NXSB":
        print(f"  not an APFS container: {head[32:36]!r}")
        return 1
    block_size, block_count = struct.unpack_from("<IQ", head, 36)
    print(f"\n  container: block size {block_size}, {block_count:,} blocks\n")

    fh.seek(0)
    found = patched = 0
    verified = 0
    chunk_blocks = 4096
    index = 0
    while True:
        chunk = fh.read(block_size * chunk_blocks)
        if not chunk:
            break
        for i in range(0, len(chunk) - block_size + 1, block_size):
            if chunk[i + MAGIC_OFF:i + MAGIC_OFF + 4] != b"APSB":
                continue
            blk = chunk[i:i + block_size]
            stored, = struct.unpack_from("<Q", blk, 0)
            if fletcher64(blk) != stored:
                continue                    # stale or torn copy, not live metadata
            verified += 1
            flags, = struct.unpack_from("<Q", blk, INCOMPAT_OFF)
            block_no = index + i // block_size
            name = blk[0x2C0:0x2C0 + 32].split(b"\x00")[0].decode("utf-8", "replace")
            print(f"    block {block_no:>8}: {name!r}  flags {flags:#x} "
                  f"({describe(flags)})")
            if not flags & SEALED:
                continue
            found += 1
            if not args.write:
                continue
            new = bytearray(blk)
            struct.pack_into("<Q", new, INCOMPAT_OFF, flags & ~SEALED)
            struct.pack_into("<Q", new, 0, fletcher64(bytes(new)))
            fh.seek(block_no * block_size)
            fh.write(bytes(new))
            fh.seek((index + chunk_blocks) * block_size)
            patched += 1
        index += chunk_blocks

    print(f"\n  {verified} volume superblocks with a valid checksum")
    print(f"  {found} of them sealed")
    if args.write:
        print(f"  {patched} patched")
    else:
        print("  nothing written; pass --write to clear the flag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
