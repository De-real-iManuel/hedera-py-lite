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

_MIRROR_HOSTS = {
    "mainnet": "mainnet-public.mirrornode.hedera.com",
    "testnet": "testnet.mirrornode.hedera.com",
}

_MIRROR_BASES = {k: f"https://{v}/api/v1" for k, v in _MIRROR_HOSTS.items()}


def mirror_base(network: str = "testnet") -> str:
    """Return the Mirror Node base URL for the given network."""
    return _MIRROR_BASES[network]


def _mirror_get(
    url: str,
    params: dict | None = None,
    timeout: int = 10,
) -> requests.Response:
    """Hardened GET for Mirror Node calls.

    Raises:
        LookupError: on HTTP 404
        RuntimeError: on any other non-2xx response
    """
    resp = requests.get(url, params=params, timeout=timeout)
    if resp.status_code == 404:
        raise LookupError(f"Not found: {url}")
    if not resp.ok:
        raise RuntimeError(
            f"Mirror Node error {resp.status_code} for {url}: {resp.text[:200]}"
        )
    logger.debug("Mirror GET %s -> %d", url, resp.status_code)
    return resp


def get_topic_messages(
    topic_id: str,
    network: str,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Fetch all HCS messages for a topic from the Mirror Node, with pagination.

    Args:
        topic_id:   Hedera topic ID, e.g. "0.0.1234"
        network:    "testnet" or "mainnet"
        start_time: Optional timestamp filter (ISO-8601 or Unix seconds string)
        end_time:   Optional timestamp filter
        limit:      Page size per request (max 100)

    Returns:
        List of raw message dicts from the Mirror Node API.

    Raises:
        LookupError: if the topic is not found (404)
        RuntimeError: on Mirror Node errors
    """
    base = mirror_base(network)
    params: dict = {"limit": min(limit, 100), "order": "asc"}
    if start_time:
        params["timestamp"] = f"gte:{start_time}"
    if end_time:
        # append second timestamp filter if start_time already set
        existing = params.get("timestamp")
        if existing:
            params["timestamp"] = [existing, f"lte:{end_time}"]
        else:
            params["timestamp"] = f"lte:{end_time}"

    messages: list[dict] = []
    url: str | None = f"{base}/topics/{topic_id}/messages"

    while url:
        resp = _mirror_get(url, params=params)
        data = resp.json()
        messages.extend(data.get("messages", []))
        next_link = data.get("links", {}).get("next")
        if next_link:
            url = f"https://{_MIRROR_HOSTS[network]}{next_link}"
            params = {}  # params are baked into the next URL
        else:
            url = None

    return messages


def _format_mirror_tx_id(tx_id_str: str) -> str:
    """Convert '0.0.X@secs.nanos' to '0.0.X-secs-nanos' for mirror node URLs."""
    account, timestamp = tx_id_str.split("@")
    return f"{account}-{timestamp.replace('.', '-')}"


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
                txs = resp.json().get("transactions", [])
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
