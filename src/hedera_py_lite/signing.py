"""
Signing layer for hedera-py-lite.

Handles key loading, algorithm detection, and transaction signing
for Ed25519 and secp256k1 keys in DER or raw hex format.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    SECP256K1,
    ECDSA,
)
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from hedera_py_lite.proto import len_field, varint, field


# ---------------------------------------------------------------------------
# Key parsing helpers
# ---------------------------------------------------------------------------

def hex_to_raw32(key_hex: str) -> bytes:
    """Extract the raw 32-byte private key from a DER-encoded or raw hex string.

    - DER Ed25519 (prefix 302e): last 32 bytes
    - DER secp256k1 (prefix 3030/3031): last 32 bytes
    - Raw 64-char hex: decoded directly (32 bytes)
    - 0x-prefixed: prefix stripped before parsing
    Raises ValueError if the decoded value is shorter than 32 bytes.
    """
    h = key_hex.strip()
    if h.startswith("0x") or h.startswith("0X"):
        h = h[2:]
    raw = bytes.fromhex(h)
    if len(raw) < 32:
        raise ValueError(f"Key too short: expected >= 32 bytes, got {len(raw)}")
    return raw[-32:]


def is_secp256k1_key(key_hex: str) -> bool:
    """Return True if the key is secp256k1 (by DER prefix or HEDERA_KEY_TYPE env var).

    DER prefixes:
      3030 / 3031 → secp256k1
      302e        → Ed25519 (returns False)
    Raw 32-byte hex defaults to Ed25519 unless HEDERA_KEY_TYPE=secp256k1.
    """
    h = key_hex.strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if h.startswith("3030") or h.startswith("3031"):
        return True
    if h.startswith("302e"):
        return False
    # Raw key — check env override
    return os.environ.get("HEDERA_KEY_TYPE", "").lower() == "secp256k1"


def load_ed25519_key(hex_str: str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a DER or raw hex string."""
    raw = hex_to_raw32(hex_str)
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_secp256k1_key(hex_str: str) -> EllipticCurvePrivateKey:
    """Load a secp256k1 private key from a DER or raw hex string."""
    from cryptography.hazmat.primitives.asymmetric.ec import derive_private_key
    raw = hex_to_raw32(hex_str)
    scalar = int.from_bytes(raw, "big")
    return derive_private_key(scalar, SECP256K1())


# ---------------------------------------------------------------------------
# Signing functions
# ---------------------------------------------------------------------------

def sign_ed25519(body_bytes: bytes, private_key: Ed25519PrivateKey) -> bytes:
    """Sign body_bytes with an Ed25519 key; return the 64-byte signature."""
    return private_key.sign(body_bytes)


def sign_secp256k1(body_bytes: bytes, private_key: EllipticCurvePrivateKey) -> bytes:
    """Sign body_bytes with a secp256k1 key; return the DER-encoded signature."""
    return private_key.sign(body_bytes, ECDSA(SHA256()))


def sign_body(body_bytes: bytes, key_hex: str) -> bytes:
    """Sign a TransactionBody and wrap it as Transaction { field 5: SignedTransaction }.

    Dispatches to Ed25519 or secp256k1 based on key type detection.
    SignaturePair field layout:
      field 3 (len) = ed25519 signature
      field 2 (len) = ecdsa_secp256k1 signature

    Returns Transaction bytes strictly longer than body_bytes.
    """
    if is_secp256k1_key(key_hex):
        priv = load_secp256k1_key(key_hex)
        pub_bytes = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
        sig_bytes = sign_secp256k1(body_bytes, priv)
        # SignaturePair: field 1 = pubKeyPrefix, field 6 = ecdsa_secp256k1
        sig_pair = len_field(1, pub_bytes) + len_field(6, sig_bytes)
    else:
        priv = load_ed25519_key(key_hex)
        pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        sig_bytes = sign_ed25519(body_bytes, priv)
        # SignaturePair: field 1 = pubKeyPrefix, field 3 = ed25519
        sig_pair = len_field(1, pub_bytes) + len_field(3, sig_bytes)

    # SignatureMap { field 1: SignaturePair }
    sig_map = len_field(1, sig_pair)

    # SignedTransaction { field 1: bodyBytes, field 2: sigMap }
    signed_tx = len_field(1, body_bytes) + len_field(2, sig_map)

    # Transaction { field 5: signedTransactionBytes }
    return len_field(5, signed_tx)
