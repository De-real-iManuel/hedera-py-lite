# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-04-04

### Added

- `export_topic_messages()` — export all HCS topic messages as JSON or CSV with auto base64 decoding, JSON parsing, and summary statistics (total messages, first/last sequence number, date range)
- `get_topic_messages()` on `HederaClient` — fetch decoded HCS messages directly without file export
- `get_topic_messages()` in `mirror.py` — paginated Mirror Node fetch with optional `start_time` / `end_time` filters
- `_mirror_get()` hardened HTTP helper — raises `LookupError` on 404, `RuntimeError` on other non-2xx responses
- `_decode_message()` helper — base64 → UTF-8 → JSON decode pipeline with silent fallback at each step
- Full test suite for all new functionality (`tests/test_export_topic_messages.py`) including property-based tests via Hypothesis

### Changed

- `mirror.py` refactored to use `_MIRROR_HOSTS` dict alongside `_MIRROR_BASES` to support pagination link resolution
- `_format_mirror_tx_id()` simplified

---

## [0.1.0] — 2026-03-31

### Added

- `HederaClient` — top-level public API for interacting with the Hedera network
- Account creation via `create_account()` with Ed25519 keypair generation
- HBAR transfers via `transfer_hbar()` with operator or custom payer support
- HCS message submission via `submit_hcs_message()` with Mirror Node sequence number polling
- Mirror Node queries — `get_balance()` and `account_exists()`
- Manual protobuf serialization layer (`proto.py`) — no generated code, no protobuf library
- Ed25519 and secp256k1 signing support (`signing.py`) — DER and raw hex key formats
- gRPC network layer (`network.py`) with node failover across testnet and mainnet
- Mirror Node REST polling layer (`mirror.py`)
- Property-based test suite using [Hypothesis](https://hypothesis.readthedocs.io/)
- Testnet and Mainnet node configuration
- Examples: `create_account.py`, `send_hbar.py`, `submit_hcs_message.py`
