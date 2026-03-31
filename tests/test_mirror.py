"""
Tests for the Mirror Node layer in hedera_py_lite.mirror.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9**
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from hedera_py_lite.mirror import (
    mirror_base,
    poll_for_account_id,
    poll_for_hcs_sequence,
    get_account_balance,
    account_exists,
)


# ---------------------------------------------------------------------------
# mirror_base
# ---------------------------------------------------------------------------

def test_mirror_base_testnet():
    url = mirror_base("testnet")
    assert "testnet" in url
    assert url.startswith("https://")


def test_mirror_base_mainnet():
    url = mirror_base("mainnet")
    assert "mainnet" in url
    assert url.startswith("https://")


def test_mirror_base_testnet_and_mainnet_differ():
    assert mirror_base("testnet") != mirror_base("mainnet")


def test_mirror_base_default_is_testnet():
    assert mirror_base() == mirror_base("testnet")


# ---------------------------------------------------------------------------
# poll_for_account_id
# ---------------------------------------------------------------------------

def _make_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def test_poll_for_account_id_returns_entity_id():
    """Returns entity_id when mirror node responds with a transaction."""
    resp = _make_response(200, {"transactions": [{"entity_id": "0.0.999"}]})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_account_id("0.0.1@1000.0", "testnet", max_attempts=1)
    assert result == "0.0.999"


def test_poll_for_account_id_raises_after_max_attempts():
    """Raises RuntimeError when entity_id is never found."""
    resp = _make_response(200, {"transactions": []})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp), \
         patch("hedera_py_lite.mirror.time.sleep"):
        with pytest.raises(RuntimeError):
            poll_for_account_id("0.0.1@1000.0", "testnet", max_attempts=2)


def test_poll_for_account_id_raises_on_non_200():
    """Raises RuntimeError when mirror node never returns 200."""
    resp = _make_response(404, {})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp), \
         patch("hedera_py_lite.mirror.time.sleep"):
        with pytest.raises(RuntimeError):
            poll_for_account_id("0.0.1@1000.0", "testnet", max_attempts=1)


def test_poll_for_account_id_retries_until_found():
    """Retries and returns entity_id on the second attempt."""
    empty_resp = _make_response(200, {"transactions": []})
    found_resp = _make_response(200, {"transactions": [{"entity_id": "0.0.42"}]})
    with patch("hedera_py_lite.mirror.requests.get", side_effect=[empty_resp, found_resp]), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_account_id("0.0.1@1000.0", "testnet", max_attempts=3)
    assert result == "0.0.42"


def test_poll_for_account_id_handles_request_exception():
    """Continues polling when requests raises an exception."""
    found_resp = _make_response(200, {"transactions": [{"entity_id": "0.0.7"}]})
    with patch("hedera_py_lite.mirror.requests.get", side_effect=[Exception("timeout"), found_resp]), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_account_id("0.0.1@1000.0", "testnet", max_attempts=3)
    assert result == "0.0.7"


# ---------------------------------------------------------------------------
# poll_for_hcs_sequence
# ---------------------------------------------------------------------------

def test_poll_for_hcs_sequence_returns_sequence_number():
    """Returns sequence number when consensus_timestamp matches."""
    tx_resp = _make_response(200, {"transactions": [{"consensus_timestamp": "1234.5678"}]})
    msg_resp = _make_response(200, {
        "messages": [{"consensus_timestamp": "1234.5678", "sequence_number": 7}]
    })
    with patch("hedera_py_lite.mirror.requests.get", side_effect=[tx_resp, msg_resp]), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_hcs_sequence("0.0.1@1000.0", "0.0.100", "testnet", max_attempts=1)
    assert result == 7


def test_poll_for_hcs_sequence_returns_none_after_max_attempts():
    """Returns None when sequence number is never found."""
    tx_resp = _make_response(200, {"transactions": []})
    with patch("hedera_py_lite.mirror.requests.get", return_value=tx_resp), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_hcs_sequence("0.0.1@1000.0", "0.0.100", "testnet", max_attempts=2)
    assert result is None


def test_poll_for_hcs_sequence_returns_none_on_non_200():
    """Returns None when mirror node never returns 200."""
    resp = _make_response(404, {})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_hcs_sequence("0.0.1@1000.0", "0.0.100", "testnet", max_attempts=1)
    assert result is None


def test_poll_for_hcs_sequence_no_timestamp_match():
    """Returns None when no message timestamp matches the transaction timestamp."""
    tx_resp = _make_response(200, {"transactions": [{"consensus_timestamp": "1234.5678"}]})
    msg_resp = _make_response(200, {
        "messages": [{"consensus_timestamp": "9999.0000", "sequence_number": 1}]
    })
    with patch("hedera_py_lite.mirror.requests.get", side_effect=[tx_resp, msg_resp]), \
         patch("hedera_py_lite.mirror.time.sleep"):
        result = poll_for_hcs_sequence("0.0.1@1000.0", "0.0.100", "testnet", max_attempts=1)
    assert result is None


# ---------------------------------------------------------------------------
# get_account_balance
# ---------------------------------------------------------------------------

def test_get_account_balance_converts_tinybars_to_hbar():
    """Returns balance in HBAR (tinybars / 100_000_000)."""
    resp = _make_response(200, {"balance": {"balance": 500_000_000}})
    resp.raise_for_status = MagicMock()
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        balance = get_account_balance("0.0.123", "testnet")
    assert balance == 5.0


def test_get_account_balance_zero():
    """Returns 0.0 for an account with zero balance."""
    resp = _make_response(200, {"balance": {"balance": 0}})
    resp.raise_for_status = MagicMock()
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        balance = get_account_balance("0.0.123", "testnet")
    assert balance == 0.0


# ---------------------------------------------------------------------------
# account_exists
# ---------------------------------------------------------------------------

def test_account_exists_returns_true_on_200():
    """Returns True when mirror node returns HTTP 200."""
    resp = _make_response(200, {})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        assert account_exists("0.0.123", "testnet") is True


def test_account_exists_returns_false_on_404():
    """Returns False when mirror node returns HTTP 404."""
    resp = _make_response(404, {})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        assert account_exists("0.0.999999", "testnet") is False


def test_account_exists_returns_false_on_exception():
    """Returns False when requests raises an exception."""
    with patch("hedera_py_lite.mirror.requests.get", side_effect=Exception("network error")):
        assert account_exists("0.0.123", "testnet") is False


def test_account_exists_returns_false_on_500():
    """Returns False for any non-200 status code."""
    resp = _make_response(500, {})
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        assert account_exists("0.0.123", "testnet") is False


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.integers(min_value=1, max_value=10**15))
@settings(max_examples=50)
def test_balance_conversion_property(tinybars):
    """
    **Validates: Requirements 6.5**

    For any tinybars value, get_account_balance returns tinybars / 100_000_000.
    """
    resp = _make_response(200, {"balance": {"balance": tinybars}})
    resp.raise_for_status = MagicMock()
    with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
        balance = get_account_balance("0.0.1", "testnet")
    assert balance == tinybars / 100_000_000


@given(st.sampled_from(["testnet", "mainnet"]))
@settings(max_examples=10)
def test_mirror_base_always_returns_https_url(network):
    """
    **Validates: Requirements 6.8, 6.9**

    mirror_base always returns an HTTPS URL for any supported network.
    """
    url = mirror_base(network)
    assert url.startswith("https://")
    assert "/api/v1" in url
