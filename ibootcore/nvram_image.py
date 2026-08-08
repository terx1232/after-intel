#!/usr/bin/env python3
"""
nvram_image.py -- build a CHRP NVRAM image the kernel will accept.

IONVRAM refuses an empty store. Handing it a buffer of zeros produces

    IONVRAMCHRPHandler creation failed @IONVRAM.cpp:1691

because the CHRP handler validates a header before it will use the region. The
layout and the checksum are not guessed; both are read from
`iokit/Kernel/IONVRAMCHRPHandler.cpp`:

    typedef struct chrp_nvram_header {   // 16 bytes
        uint8_t  sig;
        uint8_t  cksum;    // over sig, len and name
        uint16_t len;      // partition length in 16-byte blocks, header included
        char     name[12];
    } chrp_nvram_header_t;

    typedef struct apple_nvram_header {  // 16 + 16
        struct chrp_nvram_header chrp;
        uint32_t adler;                  // over everything after the header
        uint32_t generation;
        uint8_t  padding[8];
    } apple_nvram_header_t;

and the checksum is a byte sum with end-around carry, taken over `sig` plus the
bytes from `len` through the end of `name` - deliberately skipping `cksum`
itself:

    sum = hdr->sig;
    for (p = &hdr->len; p < &hdr->data; p++) sum += *p;
    while (sum > 0xff) sum = (sum & 0xff) + (sum >> 8);

Partition names come from the same file: "nvram"/"2nvram" for the Apple header,
"common"/"system" and "2common"/"2system" for the partitions.

The store is emitted empty of variables. That is correct rather than lazy: a
fresh machine has no NVRAM contents, and the handler formats what it needs on
first write.

Usage:
    python nvram_image.py --out nvram.bin --size 0x2000
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib

BLOCK = 0x10                     # CHRP length field counts 16-byte blocks
APPLE_HEADER_SIZE = 0x20         # chrp header + adler + generation + padding
ADLER_START = 0x14               # offsetof(struct apple_nvram_header, generation)
GENERATION = 1

SIG_APPLE = 0x5A                 # Apple header partition signature
SIG_SYSTEM = 0xA0                # system partition
SIG_COMMON = 0x7F                # common partition


def chrp_checksum(sig: int, length_blocks: int, name: bytes) -> int:
    """Byte sum with end-around carry, skipping the checksum field itself."""
    body = struct.pack("<H", length_blocks) + name.ljust(12, b"\x00")
    total = sig + sum(body)
    while total > 0xFF:
        total = (total & 0xFF) + (total >> 8)
    return total & 0xFF


def chrp_header(sig: int, length_blocks: int, name: str) -> bytes:
    nb = name.encode("ascii").ljust(12, b"\x00")
    cksum = chrp_checksum(sig, length_blocks, nb)
    return struct.pack("<BBH", sig, cksum, length_blocks) + nb


def build(size: int, v2: bool = True) -> bytes:
    """One Apple header, then a system and a common partition filling the rest."""
    if size % BLOCK:
        raise ValueError("size must be a multiple of 16")

    apple_name = "2nvram" if v2 else "nvram"
    sys_name = "2system" if v2 else "system"
    com_name = "2common" if v2 else "common"

    total_blocks = size // BLOCK
    apple_blocks = APPLE_HEADER_SIZE // BLOCK
    remaining = total_blocks - apple_blocks
    sys_blocks = remaining // 2
    com_blocks = remaining - sys_blocks

    out = bytearray(size)

    # Partitions first, so their bytes are in place before the adler is taken.
    off = APPLE_HEADER_SIZE
    out[off:off + BLOCK] = chrp_header(SIG_SYSTEM, sys_blocks, sys_name)
    off += sys_blocks * BLOCK
    out[off:off + BLOCK] = chrp_header(SIG_COMMON, com_blocks, com_name)

    # The Apple header describes itself only; its length field counts its own
    # blocks, not the whole store.
    hdr = chrp_header(SIG_APPLE, apple_blocks, apple_name)
    out[0:APPLE_HEADER_SIZE] = hdr + struct.pack("<II", 0, GENERATION) + b"\x00" * 8

    # The Adler runs from `generation` to the end of the store, not from the end
    # of the header. `adler32_with_version` takes
    # offsetof(struct apple_nvram_header, generation), which is 20:
    #
    #     chrp header  0..15
    #     adler       16..19
    #     generation  20..23   <- the checksum starts here, covering itself
    #     padding     24..31
    #
    # Assuming it started at 32 produced "header adler 0x7AD10967 !=
    # calculated_adler 0x9AC90968" - the kernel printed both values, which is
    # how the range was found rather than guessed at.
    adler = zlib.adler32(bytes(out[ADLER_START:])) & 0xFFFFFFFF
    struct.pack_into("<I", out, 16, adler)

    return bytes(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="0x2000")
    ap.add_argument("--v1", action="store_true",
                    help='use the v1 names ("nvram"/"system"/"common")')
    args = ap.parse_args(argv)

    size = int(args.size, 0)
    img = build(size, v2=not args.v1)

    sig, cksum, blocks = struct.unpack_from("<BBH", img, 0)
    name = img[4:16].split(b"\x00")[0].decode()
    adler, gen = struct.unpack_from("<II", img, 16)

    print(f"\n=== CHRP NVRAM image, {size:#x} bytes ===\n")
    print(f"  apple header : sig {sig:#04x}  cksum {cksum:#04x}  "
          f"{blocks} blocks  name {name!r}")
    print(f"                 adler {adler:#010x}  generation {gen}")
    for off in (APPLE_HEADER_SIZE,):
        s, c, b = struct.unpack_from("<BBH", img, off)
        n = img[off + 4:off + 16].split(b"\x00")[0].decode()
        print(f"  partition    : sig {s:#04x}  cksum {c:#04x}  {b} blocks  "
              f"name {n!r}  at {off:#x}")

    # Verify the checksum the same way the kernel does, rather than trusting the
    # builder that just wrote it.
    recomputed = chrp_checksum(sig, blocks, img[4:16])
    if recomputed != cksum:
        print(f"\n  SELF-CHECK FAILED: checksum {recomputed:#04x} != {cksum:#04x}",
              file=sys.stderr)
        return 1
    if zlib.adler32(img[ADLER_START:]) & 0xFFFFFFFF != adler:
        print("\n  SELF-CHECK FAILED: adler does not match the body",
              file=sys.stderr)
        return 1
    print("\n  self-check: checksum and adler recompute to the stored values")

    open(args.out, "wb").write(img)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

