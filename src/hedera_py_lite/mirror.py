"""
Mirror Node layer for hedera-py-lite.

REST polling against the Hedera Mirror Node for transaction confirmation
and account/balance queries.
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_MIRROR_BASES = {
    "mainnet": "https://mainnet-public.mirrornode.hedera.com/api/v1",
    "testnet": "https://testnet.mirrornode.hedera.com/api/v1",
}


def mirror_base(network: str = "testnet") -> str:
    """Return the Mirror Node base URL for the given network."""
    return _MIRROR_BASES[network]


def _format_mirror_tx_id(tx_id_str: str) -> str:
    """Convert '0.0.X@secs.nanos' to '0.0.X-secs-nanos' for mirror node URLs."""
    # Split on '@' to separate account from timestamp
    account, timestamp = tx_id_str.split("@")
    # Replace the '.' in the timestamp with '-'
    timestamp_dashed = timestamp.replace(".", "-")
    return f"{account}-{timestamp_dashed}"


def poll_for_account_id(tx_id_str: str, network: str, max_attempts: int = 20) -> str:
    """Poll the Mirror Node until the newly created account's entity_id is available.

    Raises RuntimeError after max_attempts with no result.
    Each attempt waits 3 seconds before querying.
    """
    mirror_tx_id = _format_mirror_tx_id(tx_id_str)
    url = f"{mirror_base(network)}/transactions/{mirror_tx_id}"

    for attempt in range(1, max_attempts + 1):
        time.sleep(3)
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                txs = data.get("transactions", [])
                if txs:
                    entity_id = txs[0].get("entity_id")
                    if entity_id:
                        return entity_id
        except Exception as exc:
            logger.debug("poll_for_account_id attempt %d error: %s", attempt, exc)

    raise RuntimeError(
        f"account ID not found after {max_attempts} attempts for tx {tx_id_str}"
    )


def poll_for_hcs_sequence(
    tx_id_str: str,
    topic_id: str,
    network: str,
    max_attempts: int = 15,
) -> int | None:
    """Poll the Mirror Node for the HCS sequence number assigned to a submitted message.

    Returns the integer sequence number on success, or None after max_attempts.
    Each attempt waits 2 seconds before querying.
    """
    mirror_tx_id = _format_mirror_tx_id(tx_id_str)
    base = mirror_base(network)
    tx_url = f"{base}/transactions/{mirror_tx_id}"

    for attempt in range(1, max_attempts + 1):
        time.sleep(2)
        try:
            resp = requests.get(tx_url, timeout=10)
            if resp.status_code == 200:
                txs = resp.json().get("transactions", [])
                if txs:
                    consensus_ts = txs[0].get("consensus_timestamp")
                    if consensus_ts:
                        messages_url = (
                            f"{base}/topics/{topic_id}/messages?limit=10&order=desc"
                        )
                        msg_resp = requests.get(messages_url, timeout=10)
                        if msg_resp.status_code == 200:
                            for msg in msg_resp.json().get("messages", []):
                                if msg.get("consensus_timestamp") == consensus_ts:
                                    return int(msg["sequence_number"])
        except Exception as exc:
            logger.debug("poll_for_hcs_sequence attempt %d error: %s", attempt, exc)

    logger.warning(
        "HCS sequence not found after %d attempts for tx %s", max_attempts, tx_id_str
    )
    return None


def get_account_balance(account_id: str, network: str) -> float:
    """Return the account balance in HBAR as a float."""
    url = f"{mirror_base(network)}/accounts/{account_id}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    tinybars = data["balance"]["balance"]
    return tinybars / 100_000_000


def account_exists(account_id: str, network: str) -> bool:
    """Return True if the account exists on the Mirror Node (HTTP 200), False otherwise."""
    try:
        url = f"{mirror_base(network)}/accounts/{account_id}"
        resp = requests.get(url, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False
