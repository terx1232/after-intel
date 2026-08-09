#!/usr/bin/env python3
"""
msi_frame.py -- a stand-in for the MSI frame Apple's PCIe driver expects.

AppleVirtualPlatformPCIEMSIController maps device memory index `msi-frame-index`
of the interrupt controller and reads one register from it:

    add  x8, x0, #0x40        ; doorbell, MSI_SETSPI_NS
    ldr  w8, [x0, #8]         ; the type register
    tbz  w8, #31, panic       ; kTypeRegisterValidMask -- bit 31 must be set
    ubfx w2, w8, #16, #0xd    ; base vector, 13 bits
    and  w1, w8, #0x1fff      ; vector count, 13 bits

That is GICv2m's layout - doorbell at +0x40, MSI_TYPER at +0x08 - with one
addition: a validity bit at 31 that real GICv2m does not define. Apple's VMM
provides the frame itself, so it can put whatever it likes there.

QEMU's `virt` machine has no GICv2m at all when gic-version=3; MSI goes through
the GICv3 ITS, which is a completely different programming model and whose
GITS_TYPER does not have bit 31 set. So there is nothing to point the device
tree at.

This writes a page of memory that reads back the way the driver wants, to be
loaded into spare RAM inside the arm-io window. It gets the controller past its
assertions and lets the PCI and VirtIO stack behind it come up, which is what
needs measuring next.

It is explicitly NOT a working MSI implementation: a doorbell write lands in RAM
and raises nothing. Whether that matters depends on whether the devices behind
it can be driven by INTx instead, which the boot log will say.

Usage:
    python msi_frame.py --out msiframe.bin --base 80 --count 32
"""

from __future__ import annotations

import argparse
import struct
import sys

TYPER_OFFSET = 0x08
DOORBELL_OFFSET = 0x40
VALID_BIT = 1 << 31


def build(base_vector: int, count: int, size: int = 0x10000) -> bytes:
    if base_vector >= (1 << 13) or count >= (1 << 13):
        raise ValueError("base and count are 13-bit fields")
    buf = bytearray(size)
    typer = VALID_BIT | ((base_vector & 0x1FFF) << 16) | (count & 0x1FFF)
    struct.pack_into("<I", buf, TYPER_OFFSET, typer)
    return bytes(buf)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", type=lambda s: int(s, 0), default=80,
                    help="first SPI this frame owns")
    ap.add_argument("--count", type=lambda s: int(s, 0), default=32)
    ap.add_argument("--size", type=lambda s: int(s, 0), default=0x10000)
    args = ap.parse_args(argv)

    img = build(args.base, args.count, args.size)
    (typer,) = struct.unpack_from("<I", img, TYPER_OFFSET)
    print(f"\n=== MSI frame, {args.size:#x} bytes ===\n")
    print(f"  MSI_TYPER  @{TYPER_OFFSET:#04x}  {typer:#010x}")
    print(f"    valid    bit 31      {'set' if typer & VALID_BIT else 'CLEAR'}")
    print(f"    base     bits 16-28  {(typer >> 16) & 0x1FFF}")
    print(f"    count    bits 0-12   {typer & 0x1FFF}")
    print(f"  doorbell   @{DOORBELL_OFFSET:#04x}  writes land in RAM and raise "
          f"nothing")
    open(args.out, "wb").write(img)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
