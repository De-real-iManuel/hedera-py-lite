# Contributing to hedera-py-lite

Thanks for taking the time to contribute. This document covers everything you need to get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [Submitting Changes](#submitting-changes)
- [Coding Standards](#coding-standards)
- [Reporting Bugs](#reporting-bugs)

---

## Code of Conduct

Be respectful. This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) Code of Conduct. Harassment, discrimination, or hostile behaviour of any kind will not be tolerated.

---

## Getting Started

1. Fork the repository on GitHub.
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/hedera-py-lite.git
   cd hedera-py-lite
   ```
3. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```

---

## Development Setup

Install the package in editable mode with dev dependencies:

```bash
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in your Hedera testnet credentials if you plan to run integration tests:

```bash
cp .env.example .env
```

---

## Running Tests

Run the full test suite:

```bash
pytest
```

Run a specific test file:

```bash
pytest tests/test_proto.py -v
```

Run with increased Hypothesis examples for deeper property testing:

```bash
pytest --hypothesis-seed=0
```

All tests must pass before a PR will be reviewed. CI runs the same suite automatically on every push and pull request.

---

## Project Structure

```
src/hedera_py_lite/
├── __init__.py     # Public API — exports HederaClient
├── client.py       # HederaClient — top-level user-facing class
├── proto.py        # Manual protobuf serialization primitives
├── signing.py      # Key loading, algorithm detection, transaction signing
├── network.py      # gRPC submission with node failover
└── mirror.py       # Mirror Node REST polling
tests/
├── test_proto.py   # Protobuf primitive and builder tests
├── test_signing.py # Signing layer tests
├── test_mirror.py  # Mirror Node layer tests
└── test_network.py # Network layer tests
examples/
├── create_account.py
├── send_hbar.py
└── submit_hcs_message.py
```

---

## Submitting Changes

1. Make sure all tests pass locally (`pytest`).
2. Keep commits focused — one logical change per commit.
3. Write a clear commit message:
   ```
   feat: add topic creation support
   fix: handle BUSY precheck code on mainnet nodes
   docs: update README quickstart example
   ```
   We follow [Conventional Commits](https://www.conventionalcommits.org/).
4. Push your branch and open a Pull Request against `main`.
5. Fill in the PR template — describe what changed and why.
6. A maintainer will review and merge once CI passes and the change is approved.

---

## Coding Standards

- **Python 3.11+** — use modern type hints (`str | None`, `tuple[str, str]`, etc.)
- **No external protobuf library** — all serialization is manual; keep it that way.
- **Type annotations** on all public functions.
- **Docstrings** on all public functions and classes (one-line summary + params/returns where non-obvious).
- **No bare `except`** — always catch specific exception types.
- **Tests for new behaviour** — if you add a function, add a test. Property-based tests (Hypothesis) are preferred for serialization and encoding logic.
- Keep the dependency list minimal — `grpcio`, `cryptography`, `requests` are the only runtime deps. Propose new dependencies in an issue first.

---

## Reporting Bugs

Open a [GitHub Issue](https://github.com/imanuel-dev/hedera-py-lite/issues) with:

- A minimal reproducible example
- The Python version and OS
- The full traceback if applicable

For security vulnerabilities, see [SECURITY.md](SECURITY.md) — do not open a public issue.
