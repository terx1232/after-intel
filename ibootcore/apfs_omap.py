#!/usr/bin/env python3
"""
apfs_omap.py -- resolve an APFS virtual object id to a block, independently.

APFS reports that the Base System's filesystem root tree, oid 0x1ffe, lives at
block 0x4787, and that the checksum there does not verify. Block 0x4787 is a
run of zeros with file data on either side, so one of two things is true: either
the object map really does point at nothing, or the kernel is reading the map at
a transaction the volume is not consistent at. Unsealing one superblock or both
gives the same address, which does not separate those.

This resolves the mapping without the kernel: find the newest valid container
superblock in the checkpoint descriptor ring, walk its object map to the volume
superblock, then walk the volume's own object map to the requested oid, and
check the block that comes out. If this agrees with the kernel, the live view is
genuinely empty and only the sealed path can mount the volume. If it disagrees,
the kernel is reading the wrong transaction and that is a different problem.

Usage:
    python apfs_omap.py BaseSystem-apfs.img
    python apfs_omap.py BaseSystem-apfs.img --oid 0x1ffe --oid 0x1ffc
"""

from __future__ import annotations

import argparse
import struct
import sys

BTNODE_ROOT = 0x0001
BTNODE_LEAF = 0x0002
BTNODE_FIXED_KV_SIZE = 0x0004
BTREE_INFO_SIZE = 40


def fletcher64(block: bytes) -> int:
    body = block[8:]
    sum1 = sum2 = 0
    mod = 0xFFFFFFFF
    for (word,) in struct.iter_unpack("<I", body):
        sum1 = (sum1 + word) % mod
        sum2 = (sum2 + sum1) % mod
    c1 = mod - ((sum1 + sum2) % mod)
    c2 = mod - ((sum1 + c1) % mod)
    return (c2 << 32) | c1


class Image:
    def __init__(self, path: str):
        self.fh = open(path, "rb")
        head = self.read_raw(0, 4096)
        if head[32:36] != b"NXSB":
            raise ValueError("not an APFS container")
        self.block_size, = struct.unpack_from("<I", head, 36)

    def read_raw(self, block: int, size: int) -> bytes:
        self.fh.seek(block * size)
        return self.fh.read(size)

    def block(self, n: int) -> bytes:
        return self.read_raw(n, self.block_size)

    def checked(self, n: int):
        b = self.block(n)
        stored, = struct.unpack_from("<Q", b, 0)
        return b, fletcher64(b) == stored


def newest_nxsb(img: Image):
    """The container superblock with the highest xid that checksums."""
    head = img.block(0)
    desc_blocks, = struct.unpack_from("<I", head, 0x68)
    desc_base, = struct.unpack_from("<Q", head, 0x70)
    best = (None, -1, -1)
    for i in range(desc_blocks & 0x7FFFFFFF):
        n = desc_base + i
        b, ok = img.checked(n)
        if not ok or b[32:36] != b"NXSB":
            continue
        xid, = struct.unpack_from("<Q", b, 16)
        if xid > best[1]:
            best = (b, xid, n)
    if best[0] is None:
        xid, = struct.unpack_from("<Q", head, 16)
        return head, xid, 0
    return best


def btree_entries(img: Image, node: bytes):
    """Yield (key, value) byte pairs from a b-tree node."""
    flags, level, nkeys = struct.unpack_from("<HHI", node, 32)
    toc_off, toc_len = struct.unpack_from("<HH", node, 40)
    key_base = 56 + toc_off + toc_len
    val_base = len(node) - (BTREE_INFO_SIZE if flags & BTNODE_ROOT else 0)
    fixed = bool(flags & BTNODE_FIXED_KV_SIZE)
    for i in range(nkeys):
        if fixed:
            k, v = struct.unpack_from("<HH", node, 56 + toc_off + i * 4)
            klen = vlen = None
        else:
            k, klen, v, vlen = struct.unpack_from("<HHHH", node, 56 + toc_off + i * 8)
        kstart = key_base + k
        key = node[kstart:kstart + (klen if klen is not None else 16)]
        # v is the offset from the end of the value area to the *start* of the
        # value, so the value runs forwards from there. Reading it as the end
        # instead returns the neighbouring entry's value, which walks the tree
        # into the wrong subtree and looks exactly like a missing key.
        vstart = val_base - v
        vlen = vlen if vlen is not None else (8 if not (flags & BTNODE_LEAF) else 16)
        yield key, node[vstart:vstart + vlen], flags, level


def omap_lookup(img: Image, tree_block: int, oid: int, xid_limit: int):
    """Walk a physical object-map b-tree for the newest entry at or below xid."""
    node, ok = img.checked(tree_block)
    if not ok:
        return None, f"tree root at {tree_block:#x} fails its checksum"
    while True:
        flags, level, nkeys = struct.unpack_from("<HHI", node, 32)
        best = None
        for key, val, f, lvl in btree_entries(img, node):
            if len(key) < 16:
                continue
            k_oid, k_xid = struct.unpack_from("<QQ", key, 0)
            if k_oid > oid or (k_oid == oid and k_xid > xid_limit):
                continue
            best = (k_oid, k_xid, val)
        if best is None:
            return None, f"no entry for oid {oid:#x} at level {level}"
        if flags & BTNODE_LEAF:
            if best[0] != oid:
                return None, f"nearest leaf entry is oid {best[0]:#x}"
            vflags, vsize, paddr = struct.unpack_from("<IIQ", best[2], 0)
            return (paddr, vflags, vsize, best[1]), None
        child, = struct.unpack_from("<Q", best[2], 0)
        node, ok = img.checked(child)
        if not ok:
            return None, f"child node {child:#x} fails its checksum"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--oid", action="append", default=[],
                    help="virtual oids to resolve (default: the root tree)")
    args = ap.parse_args(argv)

    img = Image(args.image)
    nxsb, xid, where = newest_nxsb(img)
    nx_omap, = struct.unpack_from("<Q", nxsb, 0xA0)
    fs_oid, = struct.unpack_from("<Q", nxsb, 0xB8)
    print(f"\n  container superblock at block {where}, xid {xid}")
    print(f"  container omap oid {nx_omap:#x}, first volume oid {fs_oid:#x}")

    omap, ok = img.checked(nx_omap)
    if not ok:
        print("  container omap fails its checksum")
        return 1
    tree, = struct.unpack_from("<Q", omap, 0x30)
    got, err = omap_lookup(img, tree, fs_oid, xid)
    if err:
        print(f"  volume lookup failed: {err}")
        return 1
    vol_block, vflags, vsize, vxid = got
    print(f"  volume superblock -> block {vol_block:#x} ({vol_block}), "
          f"xid {vxid}, flags {vflags:#x}")

    vol, ok = img.checked(vol_block)
    print(f"  volume superblock checksum: {'ok' if ok else 'BAD'}")
    incompat, = struct.unpack_from("<Q", vol, 0x38)
    vomap, root_oid = struct.unpack_from("<QQ", vol, 0x80)
    integ, = struct.unpack_from("<Q", vol, 0x400)
    print(f"  incompatible features {incompat:#x}"
          f"{'  (sealed)' if incompat & 0x20 else ''}")
    print(f"  volume omap {vomap:#x}, root tree oid {root_oid:#x}, "
          f"integrity meta oid {integ:#x}\n")

    vom, ok = img.checked(vomap)
    if not ok:
        print("  volume omap fails its checksum")
        return 1
    vtree, = struct.unpack_from("<Q", vom, 0x30)

    oids = [int(o, 0) for o in args.oid] or [root_oid, integ]
    for oid in oids:
        got, err = omap_lookup(img, vtree, oid, xid)
        if err:
            print(f"    oid {oid:#x}: {err}")
            continue
        paddr, vflags, vsize, vxid = got
        blk, ok = img.checked(paddr)
        zero = blk == b"\x00" * len(blk)
        otype, osub = struct.unpack_from("<II", blk, 24)
        print(f"    oid {oid:#x} -> block {paddr:#x} ({paddr}), xid {vxid}, "
              f"flags {vflags:#x}")
        print(f"        checksum {'ok' if ok else 'BAD'}"
              f"{', all zeros' if zero else ''}"
              f", type {otype:#x}/{osub:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
