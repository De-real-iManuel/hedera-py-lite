"""
Network layer for hedera-py-lite.

Raw gRPC submission with node failover.
"""
from __future__ import annotations

import logging

import grpc

from hedera_py_lite.proto import parse_precheck_code

logger = logging.getLogger(__name__)

PORT = 50211

TESTNET_NODES: list[tuple[str, str]] = [
    ("0.0.3", "0.testnet.hedera.com"),
    ("0.0.4", "1.testnet.hedera.com"),
    ("0.0.5", "2.testnet.hedera.com"),
    ("0.0.6", "3.testnet.hedera.com"),
    ("0.0.7", "4.testnet.hedera.com"),
]

MAINNET_NODES: list[tuple[str, str]] = [
    ("0.0.3", "35.237.200.180"),
    ("0.0.4", "35.186.191.247"),
    ("0.0.5", "35.192.2.25"),
    ("0.0.6", "35.199.161.108"),
    ("0.0.7", "35.203.82.240"),
]

_SUCCESS_CODES = {0, 10, 21, 22}
_BUSY_CODE = 12


def grpc_submit_raw(tx_bytes: bytes, host: str, port: int, method: str) -> bytes:
    """Submit raw transaction bytes via gRPC unary call. Opens and closes channel per call."""
    channel = grpc.insecure_channel(f"{host}:{port}")
    try:
        stub = channel.unary_unary(
            f"/{method}",
            request_serializer=None,
            response_deserializer=None,
        )
        resp: bytes = stub(tx_bytes, timeout=15)
        return resp
    finally:
        channel.close()


def submit_grpc(tx_bytes: bytes, method: str, nodes: list[tuple[str, str]]) -> None:
    """Submit transaction bytes to the first available node with failover.

    Iterates nodes in order:
    - Success codes (0, 10, 21, 22): stop and return
    - Code 12 (BUSY): skip to next node
    - Any other code: raise RuntimeError immediately
    - Network error: log warning, continue to next node
    - All nodes exhausted: raise RuntimeError
    """
    last_err: Exception | None = None

    for _account_id, host in nodes:
        try:
            resp = grpc_submit_raw(tx_bytes, host, PORT, method)
            code = parse_precheck_code(resp)

            if code in _SUCCESS_CODES:
                return
            elif code == _BUSY_CODE:
                logger.warning("Node %s busy (code 11), trying next", host)
                continue
            else:
                raise RuntimeError(f"precheck failed code={code}")

        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("gRPC error on node %s: %s", host, exc)
            last_err = exc
            continue

    raise RuntimeError(f"all nodes failed: {last_err}")
