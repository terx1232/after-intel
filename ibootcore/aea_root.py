#!/usr/bin/env python3
"""
aea_root.py -- find the AEA root header key by testing candidates against the
structure the header must have.

The content key is recovered (hpke.py), but the key that decrypts the root header
is derived from it and libAppleArchive keeps those labels as inline constants
rather than strings, so they cannot simply be read out.

They do not have to be guessed blindly either. `aeaContainerParamsInitWithRootHeader`
at 0xf1e8 validates two fields of the decrypted header, and a wrong key fails
them almost always:

    +0x18  compression algorithm, an ASCII character: '-', '4', 'a', 'e'
    +0x19  checksum mode: 0, 1 or 2

That is roughly a one-in-a-thousand filter per candidate, which turns a sweep
into a search with an oracle instead of a fishing trip. Candidates that pass are
printed with their plaintext so they can be judged rather than trusted.

Usage:
    python aea_root.py archive.head --key content.key
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aea_key

VALID_COMPRESSION = set(b"-4ae")
VALID_CHECKSUM = {0, 1, 2}


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, t, counter = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def looks_like_root_header(pt: bytes) -> bool:
    if len(pt) < 0x1A:
        return False
    return pt[0x18] in VALID_COMPRESSION and pt[0x19] in VALID_CHECKSUM


def candidates(key: bytes, salts):
    """(name, 32-byte key) pairs worth testing."""
    labels = [b"", b"AEA_AMK", b"AEA_RHEK", b"RHEK", b"AMK", b"AEA_SK", b"SK",
              b"AEA_CHEK", b"CHEK", b"AEA_CK", b"CK", b"AEA_HMAC", b"root header",
              b"AEA_ROOT", b"AEA1"]
    yield "key itself", key
    yield "sha256(key)", hashlib.sha256(key).digest()
    for salt_name, salt in salts:
        for lab in labels:
            yield f"hkdf({lab.decode() or 'no label'}, {salt_name})", \
                  hkdf(key, salt, lab, 32)


def try_decrypt(k: bytes, blob: bytes):
    """Yield (mode, plaintext) for the block ciphers AEA could plausibly use."""
    zero16 = b"\x00" * 16
    dec = Cipher(algorithms.AES(k), modes.CTR(zero16)).decryptor()
    yield "aes-ctr", dec.update(blob) + dec.finalize()
    dec = Cipher(algorithms.AES(k), modes.CBC(zero16)).decryptor()
    yield "aes-cbc", dec.update(blob) + dec.finalize()
    dec = Cipher(algorithms.AES(k), modes.ECB()).decryptor()
    yield "aes-ecb", dec.update(blob) + dec.finalize()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("head", help="the first bytes of the .aea")
    ap.add_argument("--key", required=True, help="the content key from hpke.py")
    ap.add_argument("--size", type=int, default=128,
                    help="bytes of container to try as the root header")
    args = ap.parse_args(argv)

    head = open(args.head, "rb").read()
    key = open(args.key, "rb").read()
    ents = aea_key.auth_entries(head)
    start = 12 + struct.unpack_from("<I", head, 8)[0]
    blob = head[start:start + args.size]

    # The salt, if there is one, most plausibly comes from the container itself.
    salts = [("empty", b""),
             ("zero32", b"\x00" * 32),
             ("first32", blob[:32]),
             ("authdata", ents.get("com.apple.wkms.auth-data", b"")[:32])]

    print(f"\n  container starts at {start:#x}; testing {args.size} bytes")
    print(f"  oracle: byte 0x18 in {sorted(VALID_COMPRESSION)}, "
          f"byte 0x19 in {sorted(VALID_CHECKSUM)}\n")

    tried = hits = 0
    for name, k in candidates(key, salts):
        for offset in (0, 32):          # a MAC may precede the header
            piece = blob[offset:offset + args.size - offset]
            for mode, pt in try_decrypt(k, piece[:len(piece) // 16 * 16]):
                tried += 1
                if looks_like_root_header(pt):
                    hits += 1
                    print(f"  HIT  {name} / {mode} / skip {offset}")
                    print(f"       {pt[:48].hex(' ')}")
    print(f"\n  {tried} attempts, {hits} passed the structure check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
