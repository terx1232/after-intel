#!/usr/bin/env python3
"""
aea_key.py -- recover the content key of an Apple Encrypted Archive.

The system volume and BaseSystem in a macOS IPSW ship as AEA. Their key is not
secret in the sense of being withheld: the archive header names a public URL
that serves the private half of the key pair the archive was wrapped to, because
the installer on a Mac has to read these files with no user credential. What is
needed is the unwrapping, and that is ordinary ECIES.

The header is "AEA1", a profile word, an auth-data length, then a list of
(uint32 length, key NUL value) entries. The ones that matter:

    com.apple.wkms.fcs-key-url   where the private key is served
    com.apple.wkms.fcs-response  {"enc-request": ..., "wrapped-key": ...}

`enc-request` is an uncompressed P-256 point - an ephemeral public key.
`wrapped-key` is 48 bytes: 32 of ciphertext and a 16-byte GCM tag.

The scheme is Apple's kSecKeyAlgorithmECIESEncryptionStandardVariableIVX963SHA256AESGCM:

    Z          = ECDH(private, ephemeral)
    K          = X9.63-KDF-SHA256(Z, sharedInfo = ephemeral point, 48 bytes)
    key, iv    = K[:32], K[32:48]
    content    = AES-256-GCM-decrypt(key, iv, wrapped-key)

Usage:
    python aea_key.py head.bin --out key.bin
    python aea_key.py head.bin --pem fcs-key.bin --out key.bin
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import urllib.request

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_private_key

MAGIC = b"AEA1"


def auth_entries(head: bytes) -> dict:
    """The auth-data list at the front of an AEA, as {key: value}."""
    if head[:4] != MAGIC:
        raise ValueError("not an AEA1 archive")
    profile, adsize = struct.unpack_from("<II", head, 4)
    out, off, end = {}, 12, 12 + adsize
    while off < end:
        (n,) = struct.unpack_from("<I", head, off)
        if n < 5:
            break
        blob = head[off + 4:off + n]
        k, _, v = blob.partition(b"\x00")
        out[k.decode("ascii", "replace")] = v
        off += n
    out["_profile"] = profile
    return out


def x963_kdf(shared: bytes, info: bytes, length: int) -> bytes:
    """ANSI X9.63 KDF with SHA-256: SHA256(Z || counter || sharedInfo)."""
    out, counter = b"", 1
    while len(out) < length:
        out += hashlib.sha256(shared + struct.pack(">I", counter) + info).digest()
        counter += 1
    return out[:length]


def unwrap(head: bytes, pem: bytes | None = None) -> bytes:
    ents = auth_entries(head)
    resp = json.loads(ents["com.apple.wkms.fcs-response"])
    ephemeral = base64.b64decode(resp["enc-request"])
    wrapped = base64.b64decode(resp["wrapped-key"])

    if pem is None:
        url = ents["com.apple.wkms.fcs-key-url"].decode().rstrip("\x00")
        with urllib.request.urlopen(url, timeout=60) as r:
            pem = r.read()

    priv = load_pem_private_key(pem, password=None)
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ephemeral)
    shared = priv.exchange(ec.ECDH(), peer)

    material = x963_kdf(shared, ephemeral, 48)
    key, iv = material[:32], material[32:48]
    return AESGCM(key).decrypt(iv, wrapped, None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("head", help="the first bytes of the .aea file")
    ap.add_argument("--pem", help="the served private key, if already fetched")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    head = open(args.head, "rb").read()
    ents = auth_entries(head)
    print(f"\n  profile {ents['_profile']}")
    for k in ents:
        if k.startswith("_"):
            continue
        print(f"    {k:<32} {len(ents[k])} bytes")

    pem = open(args.pem, "rb").read() if args.pem else None
    key = unwrap(head, pem)
    print(f"\n  content key: {len(key)} bytes")
    print(f"    {key.hex()}")
    if args.out:
        open(args.out, "wb").write(key)
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
