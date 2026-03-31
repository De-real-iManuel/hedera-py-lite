# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-31-03

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
