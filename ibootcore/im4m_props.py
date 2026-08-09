#!/usr/bin/env python3
"""
im4m_props.py -- read the manifest properties out of an Image4 manifest.

The kernel panics with "non-sensical crypto hash method:" when
`/chosen/manifest-properties` does not carry what it expects. Two attempts to
synthesise that node from names found in the kernel's string table failed,
because those are the long display labels and the manifest uses four-character
codes: BORD, CHIP, CPRO, CSEC, CEPO, SDOM and friends.

The real manifest for this platform ships inside the installer:

    AssetData/boot/Firmware/Manifests/restore/macOS Customer Software Update/
    apticket.vma2macosap.im4m

`vma2macosap` is the Apple Virtual Machine, the same platform whose kernel this
project boots. Its MANP section carries `prtp = VirtualMac2,1`, matching the
model this device tree already claims.

This walks the DER and returns the MANP properties as {tag: value}. It is a
deliberately small parser: enough structure to find a nested SET of four-char
tags, no certificate handling and no signature checking, because nothing here
verifies anything - it reads values Apple already published in a file the user
downloaded.

Usage:
    python im4m_props.py <manifest.im4m>
"""

from __future__ import annotations

import argparse
import sys


def der_read_len(buf: bytes, i: int):
    """Return (length, next_index)."""
    b = buf[i]
    i += 1
    if b < 0x80:
        return b, i
    n = b & 0x7F
    if n == 0 or n > 4:
        raise ValueError(f"unsupported length form {b:#x} at {i - 1}")
    val = int.from_bytes(buf[i:i + n], "big")
    return val, i + n


def der_read_tag(buf: bytes, i: int):
    """Return (first_tag_byte, next_index), handling the high-tag-number form.

    Apple wraps each manifest property in a private tag well above 30, which DER
    encodes as 0x1F in the low five bits followed by base-128 continuation
    bytes. Reading the tag as a single byte - the obvious thing - stops the walk
    dead at the first property and finds only the outer IM4M string.
    """
    first = buf[i]
    i += 1
    if (first & 0x1F) == 0x1F:
        while i < len(buf) and buf[i] & 0x80:
            i += 1
        i += 1
    return first, i


def walk(buf: bytes, start: int, end: int, depth: int = 0):
    """Yield (tag, header_end, content_end, depth) for each TLV in a range."""
    i = start
    while i < end - 1:
        try:
            tag, after_tag = der_read_tag(buf, i)
            length, body = der_read_len(buf, after_tag)
        except (ValueError, IndexError):
            return
        stop = body + length
        if stop > end:
            return
        yield tag, body, stop, depth
        if tag & 0x20:          # constructed
            yield from walk(buf, body, stop, depth + 1)
        i = stop


def decode_value(buf: bytes, tag: int, body: int, stop: int):
    """Turn one DER value into something a device tree can carry."""
    raw = buf[body:stop]
    if tag == 0x01:                       # BOOLEAN
        return bool(raw and raw[0])
    if tag == 0x02:                       # INTEGER
        return int.from_bytes(raw, "big")
    if tag in (0x04, 0x16, 0x0C):         # OCTET STRING, IA5String, UTF8String
        return raw
    return raw


def properties(buf: bytes) -> dict:
    """Every four-character tag in the manifest, with the value that follows it.

    Apple wraps each property as a private-tag TLV whose contents are a
    SEQUENCE of {IA5String name, value}. Rather than model that exactly, find
    the four-character names and take the next primitive value after each -
    which is what they are.
    """
    out = {}
    items = list(walk(buf, 0, len(buf)))
    for idx, (tag, body, stop, _d) in enumerate(items):
        if tag != 0x16 or stop - body != 4:      # IA5String of exactly 4 chars
            continue
        name = buf[body:stop].decode("ascii", "replace")
        if not name.isascii() or not name.isprintable():
            continue
        for tag2, body2, stop2, _d2 in items[idx + 1:idx + 4]:
            if tag2 & 0x20:                       # skip constructed wrappers
                continue
            if tag2 == 0x16 and stop2 - body2 == 4:
                break                             # that is the next property
            out[name] = decode_value(buf, tag2, body2, stop2)
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    args = ap.parse_args(argv)

    buf = open(args.manifest, "rb").read()
    if b"IM4M" not in buf[:64]:
        print("error: does not look like an IM4M manifest", file=sys.stderr)
        return 2

    props = properties(buf)
    print(f"\n=== {args.manifest}: {len(buf):,} bytes, "
          f"{len(props)} properties ===\n")
    for name, value in sorted(props.items()):
        if isinstance(value, bytes):
            text = value.decode("ascii", "replace")
            shown = repr(text) if text.isprintable() else value.hex()[:48]
        else:
            shown = repr(value)
        print(f"  {name}  {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
