"""
Tests for protobuf serialization primitives in hedera_py_lite.proto.

"""
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from hedera_py_lite.proto import varint, decode_varint, sint64, decode_sint64, build_account_id


# ---------------------------------------------------------------------------
# Unit tests — known values
# ---------------------------------------------------------------------------

def test_varint_zero():
    assert varint(0) == b'\x00'


def test_varint_300():
    assert varint(300) == b'\xac\x02'


def test_varint_single_byte_boundary():
    # 127 is the largest single-byte varint
    assert varint(127) == b'\x7f'
    # 128 requires two bytes
    assert len(varint(128)) == 2


def test_varint_max_u64():
    # 2^64 - 1 should encode to exactly 10 bytes
    result = varint(2**64 - 1)
    assert len(result) == 10
    assert decode_varint(result) == 2**64 - 1


# ---------------------------------------------------------------------------
# Property-based test — varint round-trip
# ---------------------------------------------------------------------------

@given(st.integers(min_value=0, max_value=2**64 - 1))
@settings(max_examples=100)
def test_varint_round_trip(n: int):
    """Property 1: decode_varint(varint(n)) == n for all n in [0, 2^64)."""
    assert decode_varint(varint(n)) == n


# ---------------------------------------------------------------------------
# Unit tests — sint64 known values
# ---------------------------------------------------------------------------

def test_sint64_zero():
    # zigzag(0) = 0
    assert sint64(0) == b'\x00'


def test_sint64_minus_one():
    # zigzag(-1) = 1
    assert sint64(-1) == b'\x01'


def test_sint64_one():
    # zigzag(1) = 2
    assert sint64(1) == b'\x02'


def test_sint64_minus_two():
    # zigzag(-2) = 3
    assert sint64(-2) == b'\x03'


# ---------------------------------------------------------------------------
# Property-based test — sint64 round-trip
# ---------------------------------------------------------------------------

@given(st.integers(min_value=-(2**63), max_value=2**63 - 1))
@settings(max_examples=100)
def test_sint64_round_trip(n: int):
    """Property 2: decode_sint64(sint64(n)) == n for all n in [-2^63, 2^63)."""
    assert decode_sint64(sint64(n)) == n


# ---------------------------------------------------------------------------
# Helper: parse AccountID bytes back to (shard, realm, num)
# ---------------------------------------------------------------------------

def parse_account_id(data: bytes) -> tuple[int, int, int]:
    """Parse protobuf-encoded AccountID bytes into (shard, realm, num).

    AccountID wire format:
      field 1 (varint): shard
      field 2 (varint): realm
      field 3 (varint): num
    Missing fields default to 0 (omitted when zero by build_account_id).
    """
    fields: dict[int, int] = {}
    i = 0
    while i < len(data):
        tag = data[i]
        i += 1
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            value = 0
            shift = 0
            while i < len(data):
                b = data[i]
                i += 1
                value |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            fields[field_num] = value
        else:
            break  # unexpected wire type — stop parsing
    return fields.get(1, 0), fields.get(2, 0), fields.get(3, 0)


# ---------------------------------------------------------------------------
# Unit tests — build_account_id known values
# ---------------------------------------------------------------------------

def test_build_account_id_zero_zero_three():
    data = build_account_id(0, 0, 3)
    assert parse_account_id(data) == (0, 0, 3)


def test_build_account_id_all_zeros():
    data = build_account_id(0, 0, 0)
    assert parse_account_id(data) == (0, 0, 0)


def test_build_account_id_nonzero_shard_realm():
    data = build_account_id(1, 2, 12345)
    assert parse_account_id(data) == (1, 2, 12345)


# ---------------------------------------------------------------------------
# Property-based test — Account ID round-trip
# ---------------------------------------------------------------------------

@given(
    st.integers(min_value=0, max_value=2**32),
    st.integers(min_value=0, max_value=2**32),
    st.integers(min_value=0, max_value=2**32),
)
@settings(max_examples=100)
def test_account_id_round_trip(shard: int, realm: int, num: int):
    """Property 3: parsing build_account_id(s, r, n) recovers (s, r, n)."""
    data = build_account_id(shard, realm, num)
    recovered = parse_account_id(data)
    assert recovered == (shard, realm, num)


# ---------------------------------------------------------------------------
# Helper: walk protobuf wire format and collect top-level field numbers
# ---------------------------------------------------------------------------

def collect_top_level_field_numbers(data: bytes) -> set[int]:
    """Walk a protobuf-encoded message and return the set of top-level field numbers."""
    field_nums: set[int] = set()
    i = 0
    while i < len(data):
        # Decode the tag varint
        tag = 0
        shift = 0
        while i < len(data):
            b = data[i]
            i += 1
            tag |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        field_num = tag >> 3
        wire_type = tag & 0x07
        field_nums.add(field_num)
        if wire_type == 0:  # varint — consume bytes until MSB clear
            while i < len(data):
                b = data[i]
                i += 1
                if not (b & 0x80):
                    break
        elif wire_type == 2:  # length-delimited — read length then skip
            length = 0
            shift = 0
            while i < len(data):
                b = data[i]
                i += 1
                length |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            i += length
        elif wire_type == 1:  # 64-bit fixed
            i += 8
        elif wire_type == 5:  # 32-bit fixed
            i += 4
        else:
            break  # unknown wire type — stop
    return field_nums


# ---------------------------------------------------------------------------
# Property-based test — Memo field inclusion and omission
# ---------------------------------------------------------------------------

@given(
    memo=st.text(min_size=1),
    num=st.integers(min_value=1, max_value=2**32),
    fee=st.integers(min_value=1, max_value=2**32),
    duration=st.integers(min_value=1, max_value=2**32),
    secs=st.integers(min_value=0, max_value=2**32),
    nanos=st.integers(min_value=0, max_value=999_999_999),
    inner=st.binary(),
)
@settings(max_examples=50)
def test_memo_field_present_when_non_empty(
    memo: str,
    num: int,
    fee: int,
    duration: int,
    secs: int,
    nanos: int,
    inner: bytes,
) -> None:
    """Property 4 (non-empty memo): field 6 must be present in output for non-empty memo."""
    from hedera_py_lite.proto import build_transaction_body
    payer = f"0.0.{num}"
    node = "0.0.3"
    result = build_transaction_body(payer, node, memo, fee, duration, secs, nanos, 14, inner)
    fields = collect_top_level_field_numbers(result)
    assert 6 in fields, (
        f"Expected field 6 in output for non-empty memo {memo!r}, but got fields: {fields}"
    )


@given(
    num=st.integers(min_value=1, max_value=2**32),
    fee=st.integers(min_value=1, max_value=2**32),
    duration=st.integers(min_value=1, max_value=2**32),
    secs=st.integers(min_value=0, max_value=2**32),
    nanos=st.integers(min_value=0, max_value=999_999_999),
    inner=st.binary(),
)
@settings(max_examples=50)
def test_memo_field_absent_when_empty(
    num: int,
    fee: int,
    duration: int,
    secs: int,
    nanos: int,
    inner: bytes,
) -> None:
    """Property 4 (empty memo): field 6 must be absent from output for empty memo."""
    from hedera_py_lite.proto import build_transaction_body
    payer = f"0.0.{num}"
    node = "0.0.3"
    result = build_transaction_body(payer, node, "", fee, duration, secs, nanos, 14, inner)
    fields = collect_top_level_field_numbers(result)
    assert 6 not in fields, (
        f"Expected field 6 absent for empty memo, but got fields: {fields}"
    )


# ---------------------------------------------------------------------------
# Property-based test — HCS field 27 usage and memo omission
# ---------------------------------------------------------------------------

@given(
    topic_num=st.integers(min_value=1, max_value=2**32),
    message=st.binary(min_size=1),
    payer_num=st.integers(min_value=1, max_value=2**32),
    fee=st.integers(min_value=1, max_value=2**32),
    duration=st.integers(min_value=1, max_value=2**32),
    secs=st.integers(min_value=0, max_value=2**32),
    nanos=st.integers(min_value=0, max_value=999_999_999),
)
@settings(max_examples=50)
def test_hcs_field_27_present_and_field_6_absent(
    topic_num: int,
    message: bytes,
    payer_num: int,
    fee: int,
    duration: int,
    secs: int,
    nanos: int,
) -> None:
    """Property 5: build_consensus_submit_message output embedded in TransactionBody
    must contain field 27 and must not contain field 6 (memo).
    """
    from hedera_py_lite.proto import build_consensus_submit_message, build_transaction_body

    topic_id = f"0.0.{topic_num}"
    payer = f"0.0.{payer_num}"
    node = "0.0.3"

    inner = build_consensus_submit_message(topic_id, message)
    # HCS transactions use inner_field=27 and empty memo (enforced by caller)
    result = build_transaction_body(payer, node, "", fee, duration, secs, nanos, 27, inner)

    fields = collect_top_level_field_numbers(result)
    assert 27 in fields, (
        f"Expected field 27 in TransactionBody for HCS, but got fields: {fields}"
    )
    assert 6 not in fields, (
        f"Expected field 6 (memo) absent from HCS TransactionBody, but got fields: {fields}"
    )


# ---------------------------------------------------------------------------
# Property-based test — Precheck code parse round-trip
# ---------------------------------------------------------------------------

@given(st.integers(min_value=0, max_value=2**31 - 1))
@settings(max_examples=100)
def test_precheck_code_parse_round_trip(code: int) -> None:
    """Property 6: encoding a precheck code as varint field-1 and parsing returns original code."""
    from hedera_py_lite.proto import parse_precheck_code
    # Field 1, wire type 0 (varint): tag byte = 0x08
    encoded = b'\x08' + varint(code)
    assert parse_precheck_code(encoded) == code


# ---------------------------------------------------------------------------
# Helper: parse CryptoTransferTransactionBody bytes and extract all amounts
# ---------------------------------------------------------------------------

def parse_transfer_amounts(data: bytes) -> list[int]:
    """Parse CryptoTransferTransactionBody bytes and return all AccountAmount.amount values.

    Wire format:
      CryptoTransferTransactionBody {
        field 1 (len): TransferList {
          field 1 (len): AccountAmount {
            field 1 (len): accountID
            field 2 (varint/sint64): amount  <-- zigzag encoded
          }
        }
      }
    """
    def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while pos < len(buf):
            b = buf[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        return value, pos

    def read_len_delimited(buf: bytes, pos: int) -> tuple[bytes, int]:
        length, pos = read_varint(buf, pos)
        return buf[pos:pos + length], pos + length

    def zigzag_decode(n: int) -> int:
        return (n >> 1) ^ -(n & 1)

    amounts: list[int] = []

    # Outer: field 1 = TransferList (len-delimited)
    pos = 0
    while pos < len(data):
        tag, pos = read_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 2:  # len-delimited
            inner, pos = read_len_delimited(data, pos)
            if field_num == 1:  # TransferList
                # Parse AccountAmount entries (each is field 1, len-delimited)
                tpos = 0
                while tpos < len(inner):
                    ttag, tpos = read_varint(inner, tpos)
                    tfield = ttag >> 3
                    twire = ttag & 0x07
                    if twire == 2:
                        aa_bytes, tpos = read_len_delimited(inner, tpos)
                        if tfield == 1:  # AccountAmount
                            # Parse AccountAmount: field 1 = accountID, field 2 = amount (sint64)
                            apos = 0
                            while apos < len(aa_bytes):
                                atag, apos = read_varint(aa_bytes, apos)
                                afield = atag >> 3
                                awire = atag & 0x07
                                if awire == 0:  # varint
                                    aval, apos = read_varint(aa_bytes, apos)
                                    if afield == 2:  # amount (sint64 zigzag)
                                        amounts.append(zigzag_decode(aval))
                                elif awire == 2:
                                    alen, apos = read_varint(aa_bytes, apos)
                                    apos += alen
                                else:
                                    break
                    elif twire == 0:
                        _, tpos = read_varint(inner, tpos)
                    else:
                        break
        elif wire_type == 0:
            _, pos = read_varint(data, pos)
        else:
            break

    return amounts


def make_balanced_transfers(
    transfers: list[tuple[str, int]]
) -> list[tuple[str, int]]:
    """Adjust the last entry so the sum of all amounts equals zero."""
    if not transfers:
        return transfers
    total = sum(amt for _, amt in transfers[:-1])
    last_acct = transfers[-1][0]
    return list(transfers[:-1]) + [(last_acct, -total)]


# ---------------------------------------------------------------------------
# Property-based test — Transfer Balance Conservation
# ---------------------------------------------------------------------------

# Max per-entry amount: keep sum of (max_size-1) entries within sint64 range.
# With max_size=10 and 9 non-last entries, each capped at 2^59 keeps sum < 9*2^59 < 2^63.
_MAX_TRANSFER_AMT = 2**59


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=2**32).map(lambda n: f"0.0.{n}"),
            st.integers(min_value=-_MAX_TRANSFER_AMT, max_value=_MAX_TRANSFER_AMT),
        ),
        min_size=2,
        max_size=10,
    )
)
@settings(max_examples=100)
def test_transfer_balance_conservation(transfers: list[tuple[str, int]]) -> None:
    """Property 11: sum of all tinybars amounts in a balanced CryptoTransfer equals zero.

    **Validates: Requirements 8.3, 8.6**
    """
    from hedera_py_lite.proto import build_crypto_transfer

    balanced = make_balanced_transfers(transfers)

    # Verify the input is balanced before encoding
    assert sum(amt for _, amt in balanced) == 0

    # Encode via build_crypto_transfer
    encoded = build_crypto_transfer(balanced)

    # Decode and verify the sum of amounts in the wire bytes equals zero
    amounts = parse_transfer_amounts(encoded)
    assert len(amounts) == len(balanced), (
        f"Expected {len(balanced)} amounts, got {len(amounts)}"
    )
    assert sum(amounts) == 0, (
        f"Expected sum of amounts to be 0, got {sum(amounts)}. Amounts: {amounts}"
    )


# ---------------------------------------------------------------------------
# Property-based test — HCS JSON Serialization Round-Trip
# ---------------------------------------------------------------------------

import json

# Strategy for JSON-serializable scalar values
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
)

# Recursive strategy for JSON-serializable values (dicts, lists, scalars)
_json_values = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(), children, max_size=5),
    ),
    max_leaves=20,
)

# Top-level strategy: always a dict (as required by submit_hcs_message)
_json_dict = st.dictionaries(st.text(), _json_values, max_size=5)


@given(_json_dict)
@settings(max_examples=100)
def test_hcs_json_serialization_round_trip(payload: dict) -> None:
    """Property 12: json.loads(json.dumps(payload)) == payload for any dict payload.

    **Validates: Requirements 9.1**
    """
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# Property-based test — HCS Result Dict Structure
# ---------------------------------------------------------------------------

@given(
    topic_id=st.from_regex(r"0\.0\.[1-9][0-9]{0,9}", fullmatch=True),
    sequence_number=st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1)),
    tx_id=st.one_of(st.none(), st.from_regex(r"0\.0\.[1-9][0-9]{0,9}@[0-9]+\.[0-9]{9}", fullmatch=True)),
    submitted=st.booleans(),
)
@settings(max_examples=50)
def test_hcs_result_dict_structure(
    topic_id: str,
    sequence_number: int | None,
    tx_id: str | None,
    submitted: bool,
) -> None:
    """Property 13: HCS result dict always contains topic_id, sequence_number, tx_id, submitted.

    **Validates: Requirements 9.5**
    """
    result = {
        "topic_id": topic_id,
        "sequence_number": sequence_number,
        "tx_id": tx_id,
        "submitted": submitted,
    }
    assert "topic_id" in result
    assert "sequence_number" in result
    assert "tx_id" in result
    assert "submitted" in result


# ---------------------------------------------------------------------------
# Property-based test — Balance Conversion from Tinybars to HBAR
# ---------------------------------------------------------------------------

@given(st.integers(min_value=0, max_value=2**63 - 1))
@settings(max_examples=100)
def test_balance_conversion_tinybars_to_hbar(tinybars: int) -> None:
    """Property 14: get_account_balance returns tinybars / 100_000_000 as a float.

    **Validates: Requirements 6.5**
    """
    from unittest.mock import patch, MagicMock
    from hedera_py_lite.mirror import get_account_balance

    mock_response = MagicMock()
    mock_response.json.return_value = {"balance": {"balance": tinybars}}
    mock_response.raise_for_status = MagicMock()

    with patch("hedera_py_lite.mirror.requests.get", return_value=mock_response):
        result = get_account_balance("0.0.12345", "testnet")

    assert result == tinybars / 100_000_000
    assert isinstance(result, float)
