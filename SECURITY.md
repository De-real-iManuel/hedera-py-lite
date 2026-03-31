# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue — including vulnerabilities in key handling, transaction signing, or any component that could expose private keys or allow unauthorized transactions — please report it privately.

### How to report

Send an email to the maintainer with the subject line `[SECURITY] hedera-py-lite`:

**Emmanuel Okechukwu Nwajari** — open a [GitHub Security Advisory](https://github.com/imanuel-dev/hedera-py-lite/security/advisories/new) (preferred), or contact via the email listed on the GitHub profile.

Please include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional but appreciated)

### What to expect

- Acknowledgement within **48 hours**
- A status update within **7 days**
- A fix or mitigation plan within **30 days** for confirmed vulnerabilities
- Credit in the release notes (unless you prefer to remain anonymous)

---

## Security Considerations for Users

- **Never commit private keys** to version control. Use environment variables or a secrets manager.
- The `.env` file is listed in `.gitignore` — keep it that way.
- `hedera-py-lite` does not store, transmit, or log private keys beyond the local process. The operator public key is logged at startup for verification purposes only.
- When using raw 32-byte hex keys, set `HEDERA_KEY_TYPE` explicitly to avoid algorithm misdetection.
