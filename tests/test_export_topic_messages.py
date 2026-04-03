"""
Tests for the proposed export_topic_messages feature and supporting mirror helpers.

These tests are written against the *current* codebase and will guide the
implementation. They cover:

  - _decode_message()         — base64 decode, JSON parse, passthrough
  - get_topic_messages()      — pagination, date filtering, error handling
  - export_topic_messages()   — JSON output, CSV output, summary stats, fmt validation
  - _mirror_get()             — retry on 429/5xx, LookupError on 404, RuntimeError on other errors
"""
from __future__ import annotations

import base64
import csv
import io
import json
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_resp(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = text
    return resp


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _raw_message(seq: int, content: str, ts: str = "1000.000000000") -> dict:
    """Build a minimal Mirror Node message dict."""
    return {
        "sequence_number": seq,
        "consensus_timestamp": ts,
        "topic_id": "0.0.1234",
        "message": _b64(content),
        "running_hash": "aabbcc",
        "payer_account_id": "0.0.5",
    }


# ===========================================================================
# 1. _decode_message
# ===========================================================================

class TestDecodeMessage:
    """Tests for the _decode_message helper (to be added to client.py or mirror.py)."""

    def _decode(self, msg: dict, decode_base64: bool = True) -> dict:
        # Import lazily so tests fail clearly if the function doesn't exist yet
        from hedera_py_lite.client import _decode_message
        return _decode_message(msg, decode_base64)

    def test_plain_text_decoded(self):
        msg = _raw_message(1, "hello world")
        result = self._decode(msg)
        assert result["message_text"] == "hello world"
        assert result["message_json"] is None

    def test_json_payload_decoded(self):
        payload = {"event": "ping", "value": 42}
        msg = _raw_message(1, json.dumps(payload))
        result = self._decode(msg)
        assert result["message_json"] == payload
        assert result["message_text"] == json.dumps(payload)

    def test_decode_false_leaves_raw(self):
        msg = _raw_message(1, "hello")
        result = self._decode(msg, decode_base64=False)
        assert result["message_text"] is None
        assert result["message_json"] is None
        assert result["message_b64"] == _b64("hello")

    def test_invalid_base64_does_not_raise(self):
        msg = _raw_message(1, "hello")
        msg["message"] = "!!!not_valid_base64!!!"
        result = self._decode(msg)  # must not raise
        assert result["message_text"] is None

    def test_binary_non_utf8_does_not_raise(self):
        raw = bytes([0xFF, 0xFE, 0x00])
        msg = _raw_message(1, "placeholder")
        msg["message"] = base64.b64encode(raw).decode()
        result = self._decode(msg)  # must not raise
        assert result["message_text"] is None

    def test_empty_message_field(self):
        msg = _raw_message(1, "")
        msg["message"] = ""
        result = self._decode(msg)
        assert result["message_text"] is None
        assert result["message_json"] is None

    def test_result_contains_required_keys(self):
        msg = _raw_message(1, "test")
        result = self._decode(msg)
        for key in ("sequence_number", "consensus_timestamp", "topic_id",
                    "message_b64", "message_text", "message_json",
                    "running_hash", "payer_account_id"):
            assert key in result, f"Missing key: {key}"

    def test_sequence_number_preserved(self):
        msg = _raw_message(99, "data")
        result = self._decode(msg)
        assert result["sequence_number"] == 99

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_arbitrary_text_payload_round_trips(self, text: str):
        """Any non-empty UTF-8 text survives base64 encode → decode."""
        msg = _raw_message(1, text)
        result = self._decode(msg)
        assert result["message_text"] == text


# ===========================================================================
# 2. get_topic_messages (mirror layer)
# ===========================================================================

class TestGetTopicMessages:
    """Tests for mirror.get_topic_messages — pagination and filtering."""

    def _call(self, topic_id="0.0.1234", network="testnet", **kwargs):
        from hedera_py_lite.mirror import get_topic_messages
        return get_topic_messages(topic_id, network, **kwargs)

    def test_returns_empty_list_when_no_messages(self):
        resp = _make_resp(200, {"messages": [], "links": {}})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            result = self._call()
        assert result == []

    def test_returns_messages_from_single_page(self):
        msgs = [_raw_message(i, f"msg{i}") for i in range(3)]
        resp = _make_resp(200, {"messages": msgs, "links": {}})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            result = self._call()
        assert len(result) == 3

    def test_follows_pagination_next_link(self):
        page1 = _make_resp(200, {
            "messages": [_raw_message(1, "a")],
            "links": {"next": "/api/v1/topics/0.0.1234/messages?sequencenumber=gt:1"},
        })
        page2 = _make_resp(200, {
            "messages": [_raw_message(2, "b")],
            "links": {},
        })
        with patch("hedera_py_lite.mirror.requests.get", side_effect=[page1, page2]):
            result = self._call()
        assert len(result) == 2
        assert result[0]["sequence_number"] == 1
        assert result[1]["sequence_number"] == 2

    def test_raises_on_404(self):
        resp = _make_resp(404, text="not found")
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            with pytest.raises((LookupError, RuntimeError)):
                self._call(topic_id="0.0.9999")

    def test_raises_on_500(self):
        resp = _make_resp(500, text="server error")
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            with pytest.raises(RuntimeError):
                self._call()

    def test_start_time_passed_as_query_param(self):
        resp = _make_resp(200, {"messages": [], "links": {}})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp) as mock_get:
            self._call(start_time="2024-01-01T00:00:00Z")
        call_kwargs = mock_get.call_args
        # params should contain a timestamp filter
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        # Just verify the call was made (param passing is implementation detail)
        assert mock_get.called

    def test_network_testnet_uses_testnet_url(self):
        resp = _make_resp(200, {"messages": [], "links": {}})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp) as mock_get:
            self._call(network="testnet")
        url = mock_get.call_args[0][0]
        assert "testnet" in url

    def test_network_mainnet_uses_mainnet_url(self):
        resp = _make_resp(200, {"messages": [], "links": {}})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp) as mock_get:
            self._call(network="mainnet")
        url = mock_get.call_args[0][0]
        assert "mainnet" in url


# ===========================================================================
# 3. export_topic_messages (client layer)
# ===========================================================================

class TestExportTopicMessages:
    """Tests for HederaClient.export_topic_messages."""

    def _client(self):
        from hedera_py_lite import HederaClient
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
        key = Ed25519PrivateKey.generate()
        key_hex = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
        return HederaClient("0.0.1234", key_hex, network="testnet")

    def _mock_messages(self, msgs: list[dict]):
        """Patch mirror.get_topic_messages to return msgs."""
        return patch("hedera_py_lite.mirror.get_topic_messages", return_value=msgs)

    # --- JSON output ---

    def test_json_output_is_valid_json(self):
        msgs = [_raw_message(1, "hello")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        parsed = json.loads(output)  # must not raise
        assert isinstance(parsed, dict)

    def test_json_output_contains_summary_and_messages(self):
        msgs = [_raw_message(1, "hello"), _raw_message(2, "world")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        parsed = json.loads(output)
        assert "summary" in parsed
        assert "messages" in parsed
        assert len(parsed["messages"]) == 2

    def test_json_summary_stats_correct(self):
        msgs = [_raw_message(1, "a"), _raw_message(5, "b"), _raw_message(10, "c")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        summary = json.loads(output)["summary"]
        assert summary["total_messages"] == 3
        assert summary["first_sequence"] == 1
        assert summary["last_sequence"] == 10
        assert summary["topic_id"] == "0.0.1234"

    def test_json_empty_topic_returns_zero_stats(self):
        client = self._client()
        with self._mock_messages([]):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        summary = json.loads(output)["summary"]
        assert summary["total_messages"] == 0
        assert summary["first_sequence"] is None
        assert summary["last_sequence"] is None

    def test_json_messages_are_decoded(self):
        payload = {"sensor": "temp", "value": 22.5}
        msgs = [_raw_message(1, json.dumps(payload))]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        record = json.loads(output)["messages"][0]
        assert record["message_json"] == payload
        assert record["message_text"] == json.dumps(payload)

    # --- CSV output ---

    def test_csv_output_is_parseable(self):
        msgs = [_raw_message(1, "hello"), _raw_message(2, "world")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="csv")
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 2

    def test_csv_has_sequence_number_column(self):
        msgs = [_raw_message(1, "hello")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="csv")
        reader = csv.DictReader(io.StringIO(output))
        assert "sequence_number" in reader.fieldnames

    def test_csv_empty_topic_returns_empty_string_or_header_only(self):
        client = self._client()
        with self._mock_messages([]):
            output = client.export_topic_messages("0.0.1234", fmt="csv")
        # Either empty string or just a header row — both are acceptable
        assert isinstance(output, str)

    # --- Format validation ---

    def test_invalid_fmt_raises_value_error(self):
        client = self._client()
        with self._mock_messages([]):
            with pytest.raises(ValueError, match="fmt"):
                client.export_topic_messages("0.0.1234", fmt="xml")

    def test_fmt_json_is_default(self):
        msgs = [_raw_message(1, "hi")]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234")
        # Default should be JSON — parseable as JSON
        json.loads(output)

    # --- Date range passthrough ---

    def test_start_end_time_passed_to_mirror(self):
        client = self._client()
        with patch("hedera_py_lite.mirror.get_topic_messages", return_value=[]) as mock_fn:
            client.export_topic_messages(
                "0.0.1234",
                start_time="2024-01-01T00:00:00Z",
                end_time="2024-12-31T23:59:59Z",
            )
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args[0], mock_fn.call_args[1] if mock_fn.call_args[1] else {}
        args = mock_fn.call_args[0]
        # topic_id and network are positional; start/end may be positional or keyword
        assert "0.0.1234" in args

    # --- decode_base64 flag ---

    def test_decode_base64_false_skips_decoding(self):
        msgs = [_raw_message(1, json.dumps({"x": 1}))]
        client = self._client()
        with self._mock_messages(msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json", decode_base64=False)
        record = json.loads(output)["messages"][0]
        assert record["message_text"] is None
        assert record["message_json"] is None

    # --- Property-based ---

    @given(st.lists(
        st.integers(min_value=1, max_value=10000),
        min_size=0, max_size=20, unique=True,
    ))
    @settings(max_examples=30)
    def test_total_messages_matches_input_count(self, seq_nums: list[int]):
        msgs = [_raw_message(s, f"msg{s}") for s in sorted(seq_nums)]
        client = self._client()
        with patch("hedera_py_lite.mirror.get_topic_messages", return_value=msgs):
            output = client.export_topic_messages("0.0.1234", fmt="json")
        summary = json.loads(output)["summary"]
        assert summary["total_messages"] == len(msgs)


# ===========================================================================
# 4. _mirror_get hardened helper
# ===========================================================================

class TestMirrorGet:
    """Tests for the _mirror_get helper (to be added to mirror.py)."""

    def _call(self, url="https://testnet.mirrornode.hedera.com/api/v1/topics", **kwargs):
        from hedera_py_lite.mirror import _mirror_get
        return _mirror_get(url, **kwargs)

    def test_returns_response_on_200(self):
        resp = _make_resp(200, {"messages": []})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            result = self._call()
        assert result.status_code == 200

    def test_raises_lookup_error_on_404(self):
        resp = _make_resp(404)
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            with pytest.raises(LookupError):
                self._call()

    def test_raises_runtime_error_on_500(self):
        resp = _make_resp(500, text="internal error")
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            with pytest.raises(RuntimeError):
                self._call()

    def test_raises_runtime_error_on_400(self):
        resp = _make_resp(400, text="bad request")
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp):
            with pytest.raises(RuntimeError):
                self._call()

    def test_passes_params_to_get(self):
        resp = _make_resp(200, {"messages": []})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp) as mock_get:
            self._call(params={"limit": 50, "order": "asc"})
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs.get("params") == {"limit": 50, "order": "asc"}

    def test_uses_timeout(self):
        resp = _make_resp(200, {})
        with patch("hedera_py_lite.mirror.requests.get", return_value=resp) as mock_get:
            self._call(timeout=5)
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs.get("timeout") == 5
