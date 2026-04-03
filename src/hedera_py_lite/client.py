"""
HederaClient — public API for hedera-py-lite.

Wraps proto, signing, network, and mirror layers into a clean interface
for account creation, HBAR transfers, and HCS message submission.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from hedera_py_lite import mirror
from hedera_py_lite import network as net
from hedera_py_lite.proto import (
    build_consensus_submit_message,
    build_crypto_create,
    build_crypto_transfer,
    build_transaction_body,
)
from hedera_py_lite.signing import (
    is_secp256k1_key,
    load_ed25519_key,
    load_secp256k1_key,
    sign_body,
)

logger = logging.getLogger(__name__)


class HederaClient:
    """Lightweight, JVM-free Hedera network client."""

    def __init__(
        self,
        operator_id: str,
        operator_key: str,
        network: str = "testnet",
    ) -> None:
        """Load and validate operator credentials.

        Raises RuntimeError if operator_id or operator_key is missing.
        Defaults network to "testnet".
        Derives and logs the operator public key for verification.
        """
        if not operator_id:
            raise RuntimeError("operator_id is required")
        if not operator_key:
            raise RuntimeError("operator_key is required")

        self.operator_id = operator_id
        self.operator_key = operator_key
        self.network = network

        # Derive and log public key for verification
        try:
            if is_secp256k1_key(operator_key):
                priv = load_secp256k1_key(operator_key)
                pub = priv.public_key().public_bytes(
                    Encoding.X962, PublicFormat.CompressedPoint
                )
            else:
                priv = load_ed25519_key(operator_key)
                pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            logger.info("Operator public key: %s", pub.hex())
        except Exception as exc:
            raise RuntimeError(f"Failed to load operator key: {exc}") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nodes(self) -> list[tuple[str, str]]:
        """Return the node list for the configured network."""
        if self.network == "mainnet":
            return net.MAINNET_NODES
        return net.TESTNET_NODES

    def _make_tx_id(self) -> tuple[str, int, int]:
        """Return (operator_id, secs, nanos) for a fresh transaction ID."""
        ns = time.time_ns()
        return self.operator_id, ns // 1_000_000_000, ns % 1_000_000_000

    def _tx_id_str(self, secs: int, nanos: int) -> str:
        return f"{self.operator_id}@{secs}.{nanos:09d}"

    # ------------------------------------------------------------------
    # create_account
    # ------------------------------------------------------------------

    def create_account(self, initial_balance_hbar: float = 10.0) -> tuple[str, str]:
        """Create a new Hedera account funded with initial_balance_hbar HBAR.

        Generates a fresh Ed25519 keypair, submits a CryptoCreate transaction
        (field 11) signed by the operator, then polls the mirror node for the
        new account's entity_id.

        Returns (account_id, private_key_hex).
        Raises RuntimeError on precheck failure or mirror polling timeout.
        """
        # Generate new Ed25519 keypair
        new_priv = Ed25519PrivateKey.generate()
        new_pub = new_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        new_priv_hex = new_priv.private_bytes(
            Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        ).hex()

        tinybars = int(initial_balance_hbar * 100_000_000)
        nodes = self._nodes()
        node_account, _ = nodes[0]

        payer, secs, nanos = self._make_tx_id()
        inner = build_crypto_create(new_pub, tinybars)
        body = build_transaction_body(
            payer=payer,
            node=node_account,
            memo="",
            fee=2_000_000_000,  # 20 HBAR max fee ceiling for createAccount
            duration=120,
            secs=secs,
            nanos=nanos,
            inner_field=11,
            inner=inner,
        )
        tx_bytes = sign_body(body, self.operator_key)
        net.submit_grpc(tx_bytes, "proto.CryptoService/createAccount", nodes)

        tx_id_str = self._tx_id_str(secs, nanos)
        account_id = mirror.poll_for_account_id(tx_id_str, self.network)
        return account_id, new_priv_hex

    # ------------------------------------------------------------------
    # transfer_hbar
    # ------------------------------------------------------------------

    def transfer_hbar(
        self,
        to: str,
        amount: float,
        memo: str = "",
        payer: str | None = None,
        payer_key: str | None = None,
    ) -> str:
        """Transfer HBAR from payer to recipient.

        Uses operator as default payer/signer when payer/payer_key are omitted.
        Builds a CryptoTransfer (field 14) with balanced debit/credit amounts.

        Returns the transaction ID string "account_id@secs.nanos".
        Raises RuntimeError on precheck failure.
        """
        effective_payer = payer or self.operator_id
        effective_key = payer_key or self.operator_key

        tinybars = int(amount * 100_000_000)
        transfers = [(effective_payer, -tinybars), (to, tinybars)]

        nodes = self._nodes()
        node_account, _ = nodes[0]

        _, secs, nanos = self._make_tx_id()
        inner = build_crypto_transfer(transfers)
        body = build_transaction_body(
            payer=effective_payer,
            node=node_account,
            memo=memo,
            fee=200_000_000,
            duration=120,
            secs=secs,
            nanos=nanos,
            inner_field=14,
            inner=inner,
        )
        tx_bytes = sign_body(body, effective_key)
        net.submit_grpc(tx_bytes, "proto.CryptoService/cryptoTransfer", nodes)

        return f"{effective_payer}@{secs}.{nanos:09d}"

    # ------------------------------------------------------------------
    # submit_hcs_message
    # ------------------------------------------------------------------

    def submit_hcs_message(self, topic_id: str, payload: dict | str) -> dict:
        """Submit a message to a Hedera Consensus Service topic.

        Serializes dict payloads as JSON bytes. Builds ConsensusSubmitMessage
        (field 27, memo omitted). Polls mirror node for sequence number.

        Returns dict with topic_id, sequence_number, tx_id, submitted.
        On any failure returns submitted=False without raising.
        """
        try:
            if isinstance(payload, dict):
                msg_bytes = json.dumps(payload).encode("utf-8")
            else:
                msg_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload

            nodes = self._nodes()
            node_account, _ = nodes[0]

            _, secs, nanos = self._make_tx_id()
            inner = build_consensus_submit_message(topic_id, msg_bytes)
            # memo intentionally omitted (field 27, no field 6)
            body = build_transaction_body(
                payer=self.operator_id,
                node=node_account,
                memo="",
                fee=200_000_000,
                duration=120,
                secs=secs,
                nanos=nanos,
                inner_field=27,
                inner=inner,
            )
            tx_bytes = sign_body(body, self.operator_key)
            net.submit_grpc(tx_bytes, "proto.ConsensusService/submitMessage", nodes)

            tx_id_str = self._tx_id_str(secs, nanos)
            seq = mirror.poll_for_hcs_sequence(tx_id_str, topic_id, self.network)
            return {
                "topic_id": topic_id,
                "sequence_number": seq,
                "tx_id": tx_id_str,
                "submitted": True,
            }
        except Exception as exc:
            logger.error("submit_hcs_message failed: %s", exc)
            return {
                "topic_id": topic_id,
                "sequence_number": None,
                "tx_id": None,
                "submitted": False,
            }

    # ------------------------------------------------------------------
    # get_balance / account_exists
    # ------------------------------------------------------------------

    def get_balance(self, account_id: str) -> float:
        """Return the account balance in HBAR as a float."""
        return mirror.get_account_balance(account_id, self.network)

    def account_exists(self, account_id: str) -> bool:
        """Return True if the account exists on the mirror node."""
        return mirror.account_exists(account_id, self.network)

    # ------------------------------------------------------------------
    # get_topic_messages / export_topic_messages
    # ------------------------------------------------------------------

    def get_topic_messages(
        self,
        topic_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict]:
        """Fetch all HCS messages for a topic, with optional date range.

        Returns a list of decoded message dicts (see _decode_message).
        Raises LookupError if the topic is not found, RuntimeError on Mirror Node errors.
        """
        raw = mirror.get_topic_messages(topic_id, self.network, start_time, end_time)
        return [_decode_message(m, decode_base64=True) for m in raw]

    def export_topic_messages(
        self,
        topic_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
        fmt: str = "json",
        decode_base64: bool = True,
    ) -> str:
        """Export all HCS messages for a topic as JSON or CSV.

        Args:
            topic_id:      Hedera topic ID, e.g. "0.0.1234"
            start_time:    Optional ISO-8601 or Unix timestamp (e.g. "2024-01-01T00:00:00Z")
            end_time:      Optional ISO-8601 or Unix timestamp
            fmt:           "json" (default) or "csv"
            decode_base64: Auto-decode base64 message content (default True)

        Returns:
            JSON string or CSV string with messages + summary statistics.

        Raises:
            ValueError: if fmt is not "json" or "csv"
            LookupError: if the topic is not found
            RuntimeError: on Mirror Node errors
        """
        if fmt not in ("json", "csv"):
            raise ValueError(f"fmt must be 'json' or 'csv', got {fmt!r}")

        raw = mirror.get_topic_messages(topic_id, self.network, start_time, end_time)
        records = [_decode_message(m, decode_base64) for m in raw]

        summary = {
            "topic_id": topic_id,
            "total_messages": len(records),
            "first_sequence": records[0]["sequence_number"] if records else None,
            "last_sequence": records[-1]["sequence_number"] if records else None,
            "start_time": start_time,
            "end_time": end_time,
        }

        if fmt == "json":
            return json.dumps({"summary": summary, "messages": records}, indent=2)

        # CSV output
        out = io.StringIO()
        if records:
            writer = csv.DictWriter(out, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        return out.getvalue()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _decode_message(msg: dict, decode_base64: bool = True) -> dict:
    """Normalize a raw Mirror Node message dict into a clean record.

    Attempts base64 decode → UTF-8 decode → JSON parse in sequence.
    Any step that fails is silently skipped; the raw base64 is always preserved.
    """
    content = msg.get("message", "")
    decoded_text: str | None = None
    decoded_json: dict | list | None = None

    if decode_base64 and content:
        try:
            raw_bytes = base64.b64decode(content)
            decoded_text = raw_bytes.decode("utf-8")
            try:
                decoded_json = json.loads(decoded_text)
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

    return {
        "sequence_number": msg.get("sequence_number"),
        "consensus_timestamp": msg.get("consensus_timestamp"),
        "topic_id": msg.get("topic_id"),
        "message_b64": content,
        "message_text": decoded_text,
        "message_json": decoded_json,
        "running_hash": msg.get("running_hash"),
        "payer_account_id": msg.get("payer_account_id"),
    }
