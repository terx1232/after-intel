#!/usr/bin/env python3
"""
aea.py -- decrypt an Apple Encrypted Archive (profile 1).

The content key comes from hpke.py; this turns it into the plaintext archive.

Everything here was settled against the container rather than assumed. The key
schedule was read out of libAppleArchive.dylib: the labels are inline 64-bit
immediates rather than strings (constscan.py recovered AEA_RHEK / AEA_CHEK /
AEA_SEK2 from the code), the KDF wrapper at 0x13b70 resolves to
CCKDFParametersCreateHkdf + CCDeriveKey with digest 0xa, so HKDF-SHA256 with
`derive(out, out_len, ikm, info, salt)`, and AEADDecrypt_AESCTR_MAC256_KEY640
names the 80-byte derived block: 32 bytes of HMAC key, then the AES-CTR key at
0x20, then the IV at 0x40.

The proof that it is right is structural, not a claim: byte 0x18 of the
decrypted root header is a valid compression code, 0x19 a valid checksum mode,
and all 22 reserved bytes come out zero. A wrong key does not do that.

Usage:
    python aea.py archive.aea --key content.key --probe
    python aea.py archive.aea --key content.key --out basesystem.dmg
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

COMPRESSION = {ord("-"): "none", ord("4"): "lz4", ord("b"): "lzbitmap",
               ord("e"): "lzfse", ord("f"): "lzfse", ord("x"): "lzma",
               ord("z"): "zlib"}
CHECKSUM_LEN = {0: 0, 1: 8, 2: 32}


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, t, counter = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    d = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return d.update(data) + d.finalize()


def unpack_key(block: bytes):
    """An 80-byte AEA data key: HMAC key, AES-CTR key, IV."""
    return block[:32], block[32:64], block[64:80]


class Archive:
    def __init__(self, data: bytes, key: bytes):
        if data[:4] != b"AEA1":
            raise ValueError(f"not an AEA container: {data[:4]!r}")
        self.data = data
        self.profile_word = data[4:8]
        self.profile = struct.unpack_from("<I", data, 4)[0] & 0xFFFFFF
        (auth_size,) = struct.unpack_from("<I", data, 8)
        self.auth = data[12:12 + auth_size]
        self.body_at = 12 + auth_size

        body = data[self.body_at:]
        self.salt = body[:32]
        self.main_key = hkdf(key, self.salt, b"AEA_AMK" + self.profile_word, 32)

        _, ak, iv = unpack_key(hkdf(self.main_key, b"", b"AEA_RHEK", 80))
        self.root_mac = body[32:64]
        root = ctr(ak, iv, body[64:112])
        self.root = root

        (self.original_size, self.encrypted_size) = struct.unpack_from("<QQ", root, 0)
        (self.segment_size, self.segments_per_cluster) = struct.unpack_from("<II", root, 16)
        self.compression = root[0x18]
        self.checksum = root[0x19]
        self.reserved_ok = root[0x1A:0x30] == b"\x00" * 22

    # -- clusters ---------------------------------------------------------

    def cluster_key(self, index: int) -> bytes:
        return hkdf(self.main_key, b"", b"AEA_CK" + struct.pack("<I", index), 32)

    def cluster_header_len(self) -> int:
        """Segment headers, the next cluster's header MAC, then segment MACs.

        Each segment header is 40 bytes: the two sizes and a 32-byte SHA-256 of
        the decompressed segment. The stride was measured, not assumed - the
        full segment size recurs every 40 bytes in the decrypted header.
        """
        spc = self.segments_per_cluster
        return spc * 40 + 32 + spc * 32

    def cluster_header(self, index: int, raw: bytes):
        ck = self.cluster_key(index)
        _, ak, iv = unpack_key(hkdf(ck, b"", b"AEA_CHEK", 80))
        return ctr(ak, iv, raw), ck

    def segment_key(self, ck: bytes, seg: int) -> bytes:
        return hkdf(ck, b"", b"AEA_SK" + struct.pack("<I", seg), 80)

    def describe(self) -> str:
        comp = COMPRESSION.get(self.compression, f"?{self.compression:#x}")
        return (f"  profile           {self.profile}\n"
                f"  auth data         {len(self.auth)} bytes, body at {self.body_at:#x}\n"
                f"  original size     {self.original_size:,}\n"
                f"  encrypted size    {self.encrypted_size:,}\n"
                f"  segment size      {self.segment_size:,}\n"
                f"  segments/cluster  {self.segments_per_cluster}\n"
                f"  compression       {chr(self.compression)!r} ({comp})\n"
                f"  checksum          {self.checksum} "
                f"({CHECKSUM_LEN.get(self.checksum, '?')} bytes)\n"
                f"  reserved zero     {self.reserved_ok}")


FIRST_CLUSTER = 144       # salt 32, root MAC 32, root header 48, first cluster MAC 32


def probe(a: Archive) -> int:
    """Confirm the first cluster decrypts to sane segment headers."""
    body = a.data[a.body_at:]
    print(a.describe())
    hdr_len = a.cluster_header_len()
    print(f"\n  cluster header is {hdr_len} bytes "
          f"({a.segments_per_cluster}*40 + 32 + {a.segments_per_cluster}*32)\n")

    hdr, _ = a.cluster_header(0, body[FIRST_CLUSTER:FIRST_CLUSTER + hdr_len])
    entries = [struct.unpack_from("<II", hdr, i * 40) for i in range(8)]
    sane = all(0 < o <= a.segment_size and 0 < e <= a.segment_size
               for o, e in entries)
    print(f"  cluster 0 at body+{FIRST_CLUSTER:#x}: sane={sane}")
    for i, (orig, enc) in enumerate(entries[:4]):
        print(f"      segment {i}: original {orig:>9,}  encoded {enc:>9,}")
    return FIRST_CLUSTER if sane else -1


def decompress(blob: bytes, algo: int, want: int) -> bytes:
    if len(blob) == want:
        return blob                      # stored, not compressed
    if algo in (ord("e"), ord("f")):
        import liblzfse
        return liblzfse.decompress(blob)
    if algo == ord("z"):
        import zlib
        return zlib.decompress(blob)
    if algo == ord("x"):
        import lzma
        return lzma.decompress(blob)
    if algo == ord("-"):
        return blob
    raise ValueError(f"unsupported compression {chr(algo)!r}")


def extract(a: Archive, out_path: str, limit: int = 0, verify: bool = True) -> int:
    """Walk every cluster and write the plaintext archive payload."""
    body = memoryview(a.data)[a.body_at:]
    hdr_len = a.cluster_header_len()
    spc = a.segments_per_cluster
    off = FIRST_CLUSTER
    written = bad = 0
    cluster = 0

    with open(out_path, "wb") as fh:
        while written < a.original_size:
            hdr, ck = a.cluster_header(cluster, bytes(body[off:off + hdr_len]))
            data_at = off + hdr_len
            for seg in range(spc):
                orig, enc = struct.unpack_from("<II", hdr, seg * 40)
                if orig == 0:
                    break
                digest = hdr[seg * 40 + 8:seg * 40 + 40]
                _, ak, iv = unpack_key(
                    hkdf(ck, b"", b"AEA_SK" + struct.pack("<I", seg), 80))
                raw = ctr(ak, iv, bytes(body[data_at:data_at + enc]))
                plain = decompress(raw, a.compression, orig)
                if verify and a.checksum == 2:
                    if hashlib.sha256(plain).digest() != digest:
                        bad += 1
                fh.write(plain)
                written += len(plain)
                data_at += enc
                if written >= a.original_size:
                    break
            off = data_at
            cluster += 1
            pct = 100.0 * written / a.original_size
            print(f"\r  cluster {cluster:>4}  {written:>13,} / "
                  f"{a.original_size:,} bytes  {pct:5.1f}%  "
                  f"checksum failures {bad}", end="", flush=True)
            if limit and cluster >= limit:
                break

    print()
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--key", required=True)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many clusters (for a quick check)")
    args = ap.parse_args(argv)

    data = open(args.archive, "rb").read()
    key = open(args.key, "rb").read()
    a = Archive(data, key)

    if args.probe or not args.out:
        return 0 if probe(a) > 0 else 1

    if probe(a) < 0:
        print("\n  cluster layout not recognised")
        return 1
    print()
    bad = extract(a, args.out, args.limit)
    size = __import__("os").path.getsize(args.out)
    print(f"\n  wrote {args.out}: {size:,} bytes")
    print(f"  segment checksum failures: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
