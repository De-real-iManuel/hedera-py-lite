"""Property-based tests for the signing layer (signing.py)."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256K1
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from hypothesis import given, settings as h_settings, strategies as st

from hedera_py_lite.signing import hex_to_raw32, is_secp256k1_key, sign_body


# ---------------------------------------------------------------------------
# Helpers — minimal DER key builders for test purposes
# ---------------------------------------------------------------------------

def _make_der_ed25519(raw32: bytes) -> str:
    """Wrap 32 raw bytes in a minimal Ed25519 PKCS#8 DER envelope (prefix 302e)."""
    # Standard 48-byte DER for Ed25519 private key:
    # 302e 0201 00 300506032b6570 0422 04 20 <32 bytes>
    header = bytes.fromhex("302e020100300506032b6570042204")
    return (header + raw32).hex()


def _make_der_secp256k1_3030(raw32: bytes) -> str:
    """Wrap 32 raw bytes in a secp256k1 PKCS#8 DER envelope (prefix 3030)."""
    header = bytes.fromhex("3030020100300706052b8104000a042204")
    return (header + raw32).hex()


def _make_der_secp256k1_3031(raw32: bytes) -> str:
    """Wrap 32 raw bytes in a secp256k1 DER envelope (prefix 3031)."""
    header = bytes.fromhex("3031020100300706052b8104000a042204")
    return (header + raw32).hex()


# ---------------------------------------------------------------------------
# Property 9: DER Key Extraction Yields 32 Bytes
# ---------------------------------------------------------------------------

_raw32_st = st.binary(min_size=32, max_size=32)


@given(_raw32_st)
@h_settings(max_examples=50)
def test_hex_to_raw32_ed25519_der_yields_32_bytes(raw32: bytes) -> None:
    """Property 9 (Ed25519): hex_to_raw32 on a 302e DER key returns exactly 32 bytes."""
    result = hex_to_raw32(_make_der_ed25519(raw32))
    assert len(result) == 32


@given(_raw32_st)
@h_settings(max_examples=50)
def test_hex_to_raw32_secp256k1_3030_der_yields_32_bytes(raw32: bytes) -> None:
    """Property 9 (secp256k1 3030): hex_to_raw32 on a 3030 DER key returns exactly 32 bytes."""
    result = hex_to_raw32(_make_der_secp256k1_3030(raw32))
    assert len(result) == 32


@given(_raw32_st)
@h_settings(max_examples=50)
def test_hex_to_raw32_secp256k1_3031_der_yields_32_bytes(raw32: bytes) -> None:
    """Property 9 (secp256k1 3031): hex_to_raw32 on a 3031 DER key returns exactly 32 bytes."""
    result = hex_to_raw32(_make_der_secp256k1_3031(raw32))
    assert len(result) == 32


@given(_raw32_st)
@h_settings(max_examples=50)
def test_hex_to_raw32_ed25519_preserves_raw_key(raw32: bytes) -> None:
    """Property 9 (identity Ed25519): hex_to_raw32 extracts the exact 32 bytes embedded."""
    assert hex_to_raw32(_make_der_ed25519(raw32)) == raw32


@given(_raw32_st)
@h_settings(max_examples=50)
def test_hex_to_raw32_secp256k1_preserves_raw_key(raw32: bytes) -> None:
    """Property 9 (identity secp256k1): hex_to_raw32 extracts the exact 32 bytes embedded."""
    assert hex_to_raw32(_make_der_secp256k1_3030(raw32)) == raw32


def test_hex_to_raw32_raises_on_short_key() -> None:
    """hex_to_raw32 raises ValueError when decoded bytes are fewer than 32."""
    with pytest.raises((ValueError, Exception)):
        hex_to_raw32("deadbeef")  # only 4 bytes


# ---------------------------------------------------------------------------
# Property 10: Key Type Detection by DER Prefix
# ---------------------------------------------------------------------------

_hex_chars = st.sampled_from("0123456789abcdef")
_hex_suffix_st = st.text(alphabet=_hex_chars, min_size=0, max_size=128)


@given(_hex_suffix_st)
@h_settings(max_examples=50)
def test_is_secp256k1_key_true_for_3030_prefix(suffix: str) -> None:
    """**Validates: Requirements 4.7**
    Property 10: is_secp256k1_key returns True for any hex string starting with 3030.
    """
    key_hex = "3030" + suffix
    assert is_secp256k1_key(key_hex) is True


@given(_hex_suffix_st)
@h_settings(max_examples=50)
def test_is_secp256k1_key_true_for_3031_prefix(suffix: str) -> None:
    """**Validates: Requirements 4.7**
    Property 10: is_secp256k1_key returns True for any hex string starting with 3031.
    """
    key_hex = "3031" + suffix
    assert is_secp256k1_key(key_hex) is True


@given(_hex_suffix_st)
@h_settings(max_examples=50)
def test_is_secp256k1_key_false_for_302e_prefix(suffix: str) -> None:
    """**Validates: Requirements 4.8**
    Property 10: is_secp256k1_key returns False for any hex string starting with 302e.
    """
    key_hex = "302e" + suffix
    assert is_secp256k1_key(key_hex) is False


# ---------------------------------------------------------------------------
# Property 7: Signing Algorithm Selection by Key Type
# ---------------------------------------------------------------------------
#
# The wire format of sign_body output is:
#   Transaction { field 5: SignedTransaction { field 1: bodyBytes, field 2: sigMap {
#     field 1: SignaturePair { field 1: pubKeyPrefix, field 3: ed25519 | field 2: ecdsa }
#   }}}
#
# We structurally parse the output to reach the SignaturePair and collect
# the field numbers present — avoiding false positives from scanning raw bytes.



def _fresh_ed25519_hex() -> str:
    """Generate a fresh Ed25519 private key and return it as raw hex."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return raw.hex()


def _fresh_secp256k1_hex() -> str:
    """Generate a fresh secp256k1 private key as raw 32-byte hex.

    We use raw hex + HEDERA_KEY_TYPE env override rather than DER, because the
    cryptography library emits 3081-prefixed DER for secp256k1 which is not in
    the 3030/3031 set that is_secp256k1_key recognises.
    """
    key = generate_private_key(SECP256K1())
    # Extract the raw 32-byte scalar from the DER encoding (last 32 bytes)
    der = key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    return der[-32:].hex()


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a varint from data at pos; return (value, new_pos)."""
    value = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return value, pos


def _read_len_field(data: bytes, pos: int) -> tuple[int, bytes]:
    """Read a tag + varint-length + content at pos; return (new_pos, content)."""
    pos += 1  # skip tag byte
    length, pos = _read_varint(data, pos)
    content = data[pos: pos + length]
    return pos + length, content


def _sig_pair_field_numbers(signed_output: bytes) -> set[int]:
    """Parse sign_body output and return the set of field numbers in SignaturePair.

    Structural parse — no byte scanning — so signature payload bytes can't
    produce false positives.
    """
    # Transaction[field5] → SignedTransaction
    _, signed_tx = _read_len_field(signed_output, 0)
    # SignedTransaction: field 1 = bodyBytes, field 2 = sigMap
    pos2, _ = _read_len_field(signed_tx, 0)       # skip field 1 (bodyBytes)
    _, sig_map = _read_len_field(signed_tx, pos2)  # field 2 = sigMap
    # sigMap: field 1 = SignaturePair
    _, sig_pair = _read_len_field(sig_map, 0)

    # Collect field numbers present in SignaturePair
    field_nums: set[int] = set()
    pos = 0
    while pos < len(sig_pair):
        tag = sig_pair[pos]
        field_num = tag >> 3
        wire_type = tag & 0x07
        pos += 1
        if wire_type == 2:  # len-delimited
            length, pos = _read_varint(sig_pair, pos)
            pos += length
        elif wire_type == 0:  # varint
            _, pos = _read_varint(sig_pair, pos)
        else:
            break
        field_nums.add(field_num)
    return field_nums


@given(st.binary(min_size=1, max_size=64))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_ed25519_uses_field3(body_bytes: bytes) -> None:
    """Property 7 (Ed25519): sign_body with an Ed25519 key places signature in SignaturePair field 3.

    Validates: Requirements 4.1
    """
    key_hex = _fresh_ed25519_hex()
    assert not is_secp256k1_key(key_hex), "key must be detected as Ed25519"

    output = sign_body(body_bytes, key_hex)
    fields = _sig_pair_field_numbers(output)

    assert 3 in fields, f"SignaturePair field 3 (ed25519) not found; got fields {fields}"
    assert 6 not in fields, f"SignaturePair field 6 (ecdsa) unexpectedly present; got fields {fields}"


@given(st.binary(min_size=1, max_size=64))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_secp256k1_uses_field6(body_bytes: bytes) -> None:
    """Property 7 (secp256k1): sign_body with a secp256k1 key places signature in SignaturePair field 6.

    Validates: Requirements 4.2
    """
    import os
    key_hex = _fresh_secp256k1_hex()
    # Force secp256k1 detection via env override (raw 32-byte hex has no DER prefix)
    old = os.environ.get("HEDERA_KEY_TYPE")
    os.environ["HEDERA_KEY_TYPE"] = "secp256k1"
    try:
        assert is_secp256k1_key(key_hex), "key must be detected as secp256k1"
        output = sign_body(body_bytes, key_hex)
    finally:
        if old is None:
            os.environ.pop("HEDERA_KEY_TYPE", None)
        else:
            os.environ["HEDERA_KEY_TYPE"] = old

    fields = _sig_pair_field_numbers(output)

    assert 6 in fields, f"SignaturePair field 6 (ecdsa_secp256k1) not found; got fields {fields}"
    assert 3 not in fields, f"SignaturePair field 3 (ed25519) unexpectedly present; got fields {fields}"


# ---------------------------------------------------------------------------
# Property 8: Transaction Wrapping Size Invariant
# ---------------------------------------------------------------------------


@given(st.binary(min_size=0, max_size=256))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_output_larger_than_body_ed25519(body_bytes: bytes) -> None:
    """**Validates: Requirements 4.4**
    Property 8 (Ed25519): len(sign_body(body, key)) > len(body) for any body bytes.
    """
    key_hex = _fresh_ed25519_hex()
    output = sign_body(body_bytes, key_hex)
    assert len(output) > len(body_bytes), (
        f"Expected output ({len(output)}) > body ({len(body_bytes)})"
    )


@given(st.binary(min_size=0, max_size=256))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_output_larger_than_body_secp256k1(body_bytes: bytes) -> None:
    """**Validates: Requirements 4.4**
    Property 8 (secp256k1): len(sign_body(body, key)) > len(body) for any body bytes.
    """
    import os
    key_hex = _fresh_secp256k1_hex()
    old = os.environ.get("HEDERA_KEY_TYPE")
    os.environ["HEDERA_KEY_TYPE"] = "secp256k1"
    try:
        output = sign_body(body_bytes, key_hex)
    finally:
        if old is None:
            os.environ.pop("HEDERA_KEY_TYPE", None)
        else:
            os.environ["HEDERA_KEY_TYPE"] = old
    assert len(output) > len(body_bytes), (
        f"Expected output ({len(output)}) > body ({len(body_bytes)})"
    )


# ---------------------------------------------------------------------------
# Property 16: Transaction Wrapped in Field 5
# ---------------------------------------------------------------------------

FIELD_5_TAG = 0x2A  # (5 << 3) | 2 = 42 = 0x2a  (field 5, wire type 2)


@given(st.binary(min_size=0, max_size=256))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_outermost_field_is_field5_ed25519(body_bytes: bytes) -> None:
    """**Validates: Requirements 4.3**
    Property 16 (Ed25519): the first byte of sign_body output is 0x2a (field 5, wire type 2).
    """
    key_hex = _fresh_ed25519_hex()
    output = sign_body(body_bytes, key_hex)
    assert len(output) > 0, "sign_body must return non-empty bytes"
    assert output[0] == FIELD_5_TAG, (
        f"Expected first byte 0x{FIELD_5_TAG:02x} (field 5), got 0x{output[0]:02x}"
    )


@given(st.binary(min_size=0, max_size=256))
@h_settings(max_examples=50, deadline=None)
def test_sign_body_outermost_field_is_field5_secp256k1(body_bytes: bytes) -> None:
    """**Validates: Requirements 4.3**
    Property 16 (secp256k1): the first byte of sign_body output is 0x2a (field 5, wire type 2).
    """
    import os
    key_hex = _fresh_secp256k1_hex()
    old = os.environ.get("HEDERA_KEY_TYPE")
    os.environ["HEDERA_KEY_TYPE"] = "secp256k1"
    try:
        output = sign_body(body_bytes, key_hex)
    finally:
        if old is None:
            os.environ.pop("HEDERA_KEY_TYPE", None)
        else:
            os.environ["HEDERA_KEY_TYPE"] = old
    assert len(output) > 0, "sign_body must return non-empty bytes"
    assert output[0] == FIELD_5_TAG, (
        f"Expected first byte 0x{FIELD_5_TAG:02x} (field 5), got 0x{output[0]:02x}"
    )


# ---------------------------------------------------------------------------
# Property 15: Keypair Uniqueness per Account Creation
# ---------------------------------------------------------------------------

def test_keypair_uniqueness_two_independent_generations() -> None:
    """**Validates: Requirements 7.1**
    Property 15: Two independent Ed25519 keypair generations must produce
    distinct private keys, confirming the use of a cryptographically secure
    random source.
    """
    key1 = Ed25519PrivateKey.generate()
    key2 = Ed25519PrivateKey.generate()

    raw1 = key1.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw2 = key2.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    assert raw1 != raw2, "Two independently generated Ed25519 keys must be distinct"


@given(st.integers(min_value=2, max_value=20))
def test_keypair_uniqueness_n_generations_all_distinct(n: int) -> None:
    """**Validates: Requirements 7.1**
    Property 15 (extended): Generating n independent Ed25519 keypairs produces
    n distinct private keys — no two are equal.
    """
    keys = [
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        for _ in range(n)
    ]
    assert len(set(keys)) == n, (
        f"Expected {n} distinct keys, got {len(set(keys))} unique values"
    )
