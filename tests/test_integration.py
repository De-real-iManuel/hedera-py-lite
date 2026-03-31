"""
Integration tests against the real Hedera Testnet.

These tests require a funded testnet account. Credentials are loaded
exclusively from environment variables — never hardcoded.

Run with:
    pytest tests/test_integration.py -v -s

Skip automatically when HEDERA_OPERATOR_ID is not set (e.g. in CI).
"""
from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available (dev convenience only)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Skip the entire module when credentials are absent
# ---------------------------------------------------------------------------
_OPERATOR_ID = os.environ.get("HEDERA_OPERATOR_ID", "")
_OPERATOR_KEY = os.environ.get("HEDERA_OPERATOR_KEY", "")
_NETWORK = os.environ.get("HEDERA_NETWORK", "testnet")
_TOPIC_ID = os.environ.get("HEDERA_TOPIC_ID", "")

pytestmark = pytest.mark.skipif(
    not (_OPERATOR_ID and _OPERATOR_KEY),
    reason="HEDERA_OPERATOR_ID / HEDERA_OPERATOR_KEY not set — skipping integration tests",
)


# ---------------------------------------------------------------------------
# Shared client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from hedera_py_lite import HederaClient
    return HederaClient(
        operator_id=_OPERATOR_ID,
        operator_key=_OPERATOR_KEY,
        network=_NETWORK,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_client_initializes(client):
    """Client loads credentials and derives public key without error."""
    assert client.operator_id == _OPERATOR_ID
    assert client.network == _NETWORK


def test_operator_account_exists(client):
    """Operator account is visible on the Mirror Node."""
    assert client.account_exists(_OPERATOR_ID), (
        f"Operator account {_OPERATOR_ID} not found on {_NETWORK} mirror node"
    )


def test_operator_balance_is_positive(client):
    """Operator account has a positive HBAR balance."""
    balance = client.get_balance(_OPERATOR_ID)
    assert balance > 0, (
        f"Expected positive balance for {_OPERATOR_ID}, got {balance} HBAR"
    )
    print(f"\nOperator balance: {balance:.8f} HBAR")


def test_create_account(client):
    """Creates a new account on testnet and confirms it via Mirror Node."""
    account_id, private_key_hex = client.create_account(initial_balance_hbar=5.0)

    assert account_id, "Expected a non-empty account ID"
    assert account_id.startswith("0.0."), f"Unexpected account ID format: {account_id}"
    assert len(private_key_hex) == 64, (
        f"Expected 64-char raw hex private key, got length {len(private_key_hex)}"
    )

    # Confirm the new account is visible on the mirror node
    assert client.account_exists(account_id), (
        f"Newly created account {account_id} not found on mirror node"
    )

    print(f"\nCreated account: {account_id}")
    # Private key intentionally not printed


def test_transfer_hbar(client):
    """Transfers a small amount of HBAR to the Hedera fee collection account."""
    # 0.0.98 is the Hedera fee collection account — safe recipient for tests
    recipient = "0.0.98"
    amount = 0.1

    tx_id = client.transfer_hbar(to=recipient, amount=amount, memo="hedera-py-lite integration test")

    assert tx_id, "Expected a non-empty transaction ID"
    assert "@" in tx_id, f"Unexpected tx_id format: {tx_id}"
    print(f"\nTransfer tx_id: {tx_id}")


@pytest.mark.skipif(
    not _TOPIC_ID,
    reason="HEDERA_TOPIC_ID not set — skipping HCS test",
)
def test_submit_hcs_message(client):
    """Submits a message to an HCS topic and confirms the sequence number."""
    payload = {
        "event": "integration_test",
        "source": "hedera-py-lite",
        "network": _NETWORK,
    }

    result = client.submit_hcs_message(topic_id=_TOPIC_ID, payload=payload)

    assert result["submitted"] is True, f"HCS submission failed: {result}"
    assert result["topic_id"] == _TOPIC_ID
    assert result["tx_id"] is not None
    assert result["sequence_number"] is not None
    assert isinstance(result["sequence_number"], int)

    print(f"\nHCS sequence number: {result['sequence_number']}")
    print(f"HCS tx_id: {result['tx_id']}")
