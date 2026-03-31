"""
Tests for the network layer in hedera_py_lite.network.

Validates: Requirements 5.1–5.7
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hedera_py_lite.network import (
    MAINNET_NODES,
    TESTNET_NODES,
    PORT,
    submit_grpc,
)
from hedera_py_lite.proto import varint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode_precheck(code: int) -> bytes:
    """Encode a precheck code as a minimal gRPC response (field 1, varint)."""
    return b"\x08" + varint(code)


def _mock_raw(code: int):
    """Return a mock for grpc_submit_raw that yields the given precheck code."""
    with patch(
        "hedera_py_lite.network.grpc_submit_raw",
        return_value=_encode_precheck(code),
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# Node list sanity checks
# ---------------------------------------------------------------------------

def test_testnet_nodes_non_empty():
    assert len(TESTNET_NODES) > 0


def test_mainnet_nodes_non_empty():
    assert len(MAINNET_NODES) > 0


def test_port_is_50211():
    """Requirement 5.7: gRPC port must be 50211."""
    assert PORT == 50211


def test_testnet_nodes_are_tuples_of_strings():
    for account_id, host in TESTNET_NODES:
        assert isinstance(account_id, str)
        assert isinstance(host, str)
        assert account_id.startswith("0.0.")


def test_mainnet_nodes_are_tuples_of_strings():
    for account_id, host in MAINNET_NODES:
        assert isinstance(account_id, str)
        assert isinstance(host, str)
        assert account_id.startswith("0.0.")


# ---------------------------------------------------------------------------
# Success codes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [0, 10, 21, 22])
def test_submit_grpc_succeeds_on_success_codes(code: int):
    """Requirement 5.2: codes 0, 10, 21, 22 are treated as success."""
    nodes = [("0.0.3", "node.example.com")]
    with patch(
        "hedera_py_lite.network.grpc_submit_raw",
        return_value=_encode_precheck(code),
    ):
        submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)  # must not raise


# ---------------------------------------------------------------------------
# BUSY code 
# ---------------------------------------------------------------------------

def test_submit_grpc_skips_busy_node_and_tries_next():
    """Requirement 5.3: code 12 (BUSY) causes the next node to be tried."""
    nodes = [("0.0.3", "busy.example.com"), ("0.0.4", "ok.example.com")]
    responses = [_encode_precheck(12), _encode_precheck(0)]
    with patch("hedera_py_lite.network.grpc_submit_raw", side_effect=responses):
        submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)  # must not raise


def test_submit_grpc_raises_if_all_nodes_busy():
    """Requirement 5.5: raises RuntimeError when all nodes return BUSY."""
    nodes = [("0.0.3", "a.example.com"), ("0.0.4", "b.example.com")]
    with patch(
        "hedera_py_lite.network.grpc_submit_raw",
        return_value=_encode_precheck(12),
    ):
        with pytest.raises(RuntimeError):
            submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)


# ---------------------------------------------------------------------------
# Non-success, non-busy codes 
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [4, 7, 11, 330])
def test_submit_grpc_raises_on_error_code(code: int):
    """Requirement 5.4: any code other than 0, 10, 12, 21, 22 raises RuntimeError immediately."""
    nodes = [("0.0.3", "node.example.com"), ("0.0.4", "node2.example.com")]
    with patch(
        "hedera_py_lite.network.grpc_submit_raw",
        return_value=_encode_precheck(code),
    ):
        with pytest.raises(RuntimeError, match=f"code={code}"):
            submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)


def test_submit_grpc_does_not_retry_on_error_code():
    """Requirement 5.4: raises immediately on error code without trying remaining nodes."""
    nodes = [("0.0.3", "a.example.com"), ("0.0.4", "b.example.com")]
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _encode_precheck(4)  # PAYER_ACCOUNT_NOT_FOUND

    with patch("hedera_py_lite.network.grpc_submit_raw", side_effect=side_effect):
        with pytest.raises(RuntimeError):
            submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)

    assert call_count == 1, "Should stop after first error code, not retry other nodes"


# ---------------------------------------------------------------------------
# Network errors 
# ---------------------------------------------------------------------------

def test_submit_grpc_continues_on_network_error():
    """Requirement 5.6: network errors are logged and the next node is tried."""
    nodes = [("0.0.3", "dead.example.com"), ("0.0.4", "ok.example.com")]
    responses = [Exception("connection refused"), _encode_precheck(0)]
    with patch("hedera_py_lite.network.grpc_submit_raw", side_effect=responses):
        submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)  # must not raise


def test_submit_grpc_raises_after_all_nodes_fail_with_network_error():
    """Requirement 5.5: raises RuntimeError when all nodes fail with network errors."""
    nodes = [("0.0.3", "a.example.com"), ("0.0.4", "b.example.com")]
    with patch(
        "hedera_py_lite.network.grpc_submit_raw",
        side_effect=Exception("timeout"),
    ):
        with pytest.raises(RuntimeError, match="all nodes failed"):
            submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)


def test_submit_grpc_raises_on_empty_node_list():
    """Edge case: empty node list raises RuntimeError."""
    with pytest.raises(RuntimeError):
        submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", [])


# ---------------------------------------------------------------------------
# Node ordering
# ---------------------------------------------------------------------------

def test_submit_grpc_tries_nodes_in_order():
    """Requirement 5.1: nodes are tried in the order provided."""
    tried: list[str] = []

    def side_effect(tx_bytes, host, port, method):
        tried.append(host)
        if host == "first.example.com":
            raise Exception("down")
        return _encode_precheck(0)

    nodes = [("0.0.3", "first.example.com"), ("0.0.4", "second.example.com")]
    with patch("hedera_py_lite.network.grpc_submit_raw", side_effect=side_effect):
        submit_grpc(b"tx", "proto.CryptoService/cryptoTransfer", nodes)

    assert tried == ["first.example.com", "second.example.com"]
