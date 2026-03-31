"""
Protobuf serialization primitives for the Hedera wire format.

Manual protobuf encoding — no protoc-generated code, no protobuf library.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def varint(n: int) -> bytes:
    """Encode an unsigned integer as a little-endian base-128 varint."""
    buf = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            break
    return bytes(buf)


def decode_varint(data: bytes) -> int:
    """Decode a varint from bytes, returning the integer value."""
    value = 0
    shift = 0
    for b in data:
        value |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return value


def sint64(n: int) -> bytes:
    """Zigzag-encode a signed 64-bit integer and return as varint bytes."""
    encoded = (n << 1) ^ (n >> 63)
    return varint(encoded & 0xFFFFFFFFFFFFFFFF)


def decode_sint64(data: bytes) -> int:
    """Decode a zigzag-encoded varint from bytes, returning the signed integer."""
    encoded = decode_varint(data)
    return (encoded >> 1) ^ -(encoded & 1)


def int64(n: int) -> bytes:
    """Encode a signed 64-bit integer as a varint using two's complement."""
    if n < 0:
        n = n + (1 << 64)
    return varint(n)


def field(field_num: int, wire_type: int, data: bytes) -> bytes:
    """Encode a protobuf field tag followed by data."""
    return varint((field_num << 3) | wire_type) + data


def len_field(field_num: int, data: bytes) -> bytes:
    """Encode a length-delimited (wire type 2) protobuf field."""
    return field(field_num, 2, varint(len(data)) + data)


def u64_field(field_num: int, value: int) -> bytes:
    """Encode an unsigned 64-bit integer as a varint field (wire type 0)."""
    return field(field_num, 0, varint(value))


def i64_field(field_num: int, value: int) -> bytes:
    """Encode a signed 64-bit integer (two's complement) as a varint field."""
    return field(field_num, 0, int64(value))


def s64_field(field_num: int, value: int) -> bytes:
    """Encode a zigzag sint64 as a varint field (wire type 0)."""
    return field(field_num, 0, sint64(value))


# ---------------------------------------------------------------------------
# Hedera-specific builders
# ---------------------------------------------------------------------------

def build_account_id(shard: int, realm: int, num: int) -> bytes:
    """Encode a Hedera AccountID as protobuf bytes."""
    data = b""
    if shard:
        data += u64_field(1, shard)
    if realm:
        data += u64_field(2, realm)
    data += u64_field(3, num)
    return data


def build_transaction_id(account_id: str, secs: int, nanos: int) -> bytes:
    """Encode a Hedera TransactionID as protobuf bytes."""
    parts = account_id.split(".")
    acct = build_account_id(int(parts[0]), int(parts[1]), int(parts[2]))
    ts = i64_field(1, secs) + i64_field(2, nanos)
    return len_field(1, ts) + len_field(2, acct)


def build_transaction_body(
    payer: str,
    node: str,
    memo: str,
    fee: int,
    duration: int,
    secs: int,
    nanos: int,
    inner_field: int,
    inner: bytes,
) -> bytes:
    """Assemble a Hedera TransactionBody in ascending field-number order."""
    body = len_field(1, build_transaction_id(payer, secs, nanos))
    np = node.split(".")
    body += len_field(2, build_account_id(int(np[0]), int(np[1]), int(np[2])))
    body += u64_field(3, fee)
    body += len_field(4, i64_field(1, duration))
    if memo:
        body += len_field(6, memo.encode("utf-8"))
    body += len_field(inner_field, inner)
    return body


def build_crypto_transfer(transfers: list[tuple[str, int]]) -> bytes:
    """Encode a CryptoTransferTransactionBody from a list of (account_id, tinybars) pairs."""
    transfer_list = b""
    for acct_str, amount in transfers:
        parts = acct_str.split(".")
        acct = build_account_id(int(parts[0]), int(parts[1]), int(parts[2]))
        aa = len_field(1, acct) + s64_field(2, amount)
        transfer_list += len_field(1, aa)
    return len_field(1, transfer_list)


def build_crypto_create(pub_key_bytes: bytes, initial_tinybars: int) -> bytes:
    """Encode a CryptoCreateTransactionBody.

    Key proto oneof field numbers (basic_types.proto):
      field 1 = contractID  (NOT for raw public keys)
      field 2 = ed25519     (32-byte raw Ed25519 public key)
      field 3 = RSA_3072    (unsupported)
      field 4 = ECDSA_384   (unsupported)
      field 6 = ECDSA_secp256k1 (33-byte compressed)
    """
    key_proto = len_field(2, pub_key_bytes)   # field 2 = ed25519
    body = len_field(1, key_proto)            # CryptoCreateTransactionBody field 1 = key
    body += u64_field(2, initial_tinybars)    # field 2 = initialBalance
    body += len_field(9, i64_field(1, 7_776_000))  # field 9 = autoRenewPeriod
    return body


def build_consensus_submit_message(topic_id: str, message: bytes) -> bytes:
    """Encode a ConsensusSubmitMessageTransactionBody (field 1=topicID, field 2=message)."""
    topic_num = int(topic_id.split(".")[-1])
    topic_bytes = build_account_id(0, 0, topic_num)
    return len_field(1, topic_bytes) + len_field(2, message)


def parse_precheck_code(resp: bytes) -> int:
    """Parse the integer precheck code from a Hedera gRPC response (field 1, varint)."""
    if not resp:
        return 0
    i = 0
    while i < len(resp):
        tag = resp[i]
        i += 1
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value = 0
            shift = 0
            while i < len(resp):
                b = resp[i]
                i += 1
                value |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            if field_num == 1:
                return value
        else:
            break
    return 0
