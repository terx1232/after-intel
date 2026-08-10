#!/usr/bin/env python3
"""
hpke.py -- RFC 9180 HPKE, base mode, DHKEM(P-256, HKDF-SHA256) / HKDF-SHA256 /
AES-256-GCM.

This is the scheme Apple wraps AEA content keys with, and the binary says so
outright. `usr/libexec/diskimagesiod` on the restore ramdisk imports:

    CryptoKit.HPKE.Ciphersuite.P256_SHA256_AES_GCM_256
    CryptoKit.HPKE.Recipient(privateKey:ciphersuite:info:encapsulatedKey:)
    CryptoKit.HPKE.Recipient.open(_:)

which names the ciphersuite exactly. So the archive's `enc-request` is HPKE's
encapsulated key, `wrapped-key` is the sealed ciphertext, and the private key
served from com.apple.wkms.fcs-key-url is the recipient key.

133 hand-rolled ECIES combinations failed before this was found, for the good
reason that HPKE is not ECIES: the KEM hashes the encapsulated key *and* the
recipient's public key into the shared secret, and the key schedule mixes a mode
byte and two more hashes on top. None of that appears in a plain X9.63 or HKDF
derivation.

Usage:
    python hpke.py --priv key.pem --enc enc.bin --ct wrapped.bin
    python hpke.py --priv key.pem --enc enc.bin --ct wrapped.bin --info ""
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import struct
import sys

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEM_ID = 0x0010          # DHKEM(P-256, HKDF-SHA256)
KDF_ID = 0x0001          # HKDF-SHA256
AEAD_ID = 0x0002         # AES-256-GCM
NSECRET, NK, NN = 32, 32, 12
HASH_LEN = 32

VERSION = b"HPKE-v1"


def i2osp(n: int, length: int) -> bytes:
    return n.to_bytes(length, "big")


def extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def expand(prk: bytes, info: bytes, length: int) -> bytes:
    out, t, counter = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def labeled_extract(suite_id: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    return extract(salt, VERSION + suite_id + label + ikm)


def labeled_expand(suite_id: bytes, prk: bytes, label: bytes,
                   info: bytes, length: int) -> bytes:
    return expand(prk, i2osp(length, 2) + VERSION + suite_id + label + info, length)


def kem_suite_id() -> bytes:
    return b"KEM" + i2osp(KEM_ID, 2)


def hpke_suite_id() -> bytes:
    return b"HPKE" + i2osp(KEM_ID, 2) + i2osp(KDF_ID, 2) + i2osp(AEAD_ID, 2)


def decap(priv, enc: bytes) -> bytes:
    """DHKEM decapsulation: the shared secret from enc and the recipient key."""
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), enc)
    dh = priv.exchange(ec.ECDH(), peer)
    pk_rm = priv.public_key().public_bytes(ser.Encoding.X962,
                                           ser.PublicFormat.UncompressedPoint)
    kem_context = enc + pk_rm
    sid = kem_suite_id()
    eae_prk = labeled_extract(sid, b"", b"eae_prk", dh)
    return labeled_expand(sid, eae_prk, b"shared_secret", kem_context, NSECRET)


def key_schedule(shared_secret: bytes, info: bytes):
    """Base mode: no PSK, mode byte 0."""
    sid = hpke_suite_id()
    psk_id_hash = labeled_extract(sid, b"", b"psk_id_hash", b"")
    info_hash = labeled_extract(sid, b"", b"info_hash", info)
    context = bytes([0x00]) + psk_id_hash + info_hash
    secret = labeled_extract(sid, shared_secret, b"secret", b"")
    key = labeled_expand(sid, secret, b"key", context, NK)
    base_nonce = labeled_expand(sid, secret, b"base_nonce", context, NN)
    return key, base_nonce


def open_message(priv, enc: bytes, ciphertext: bytes,
                 info: bytes = b"", aad: bytes = b"") -> bytes:
    key, nonce = key_schedule(decap(priv, enc), info)
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--priv", required=True, help="recipient private key, PEM")
    ap.add_argument("--enc", required=True, help="encapsulated key")
    ap.add_argument("--ct", required=True, help="sealed ciphertext")
    ap.add_argument("--info", default="", help="HPKE info string")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    priv = ser.load_pem_private_key(open(args.priv, "rb").read(), password=None)
    enc = open(args.enc, "rb").read()
    ct = open(args.ct, "rb").read()

    pt = open_message(priv, enc, ct, args.info.encode())
    print(f"\n  opened: {len(pt)} bytes")
    print(f"    {pt.hex()}")
    if args.out:
        open(args.out, "wb").write(pt)
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
