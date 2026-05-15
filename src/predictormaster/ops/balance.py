"""Polygon balance queries for the ops dashboard.

Reports:
  - USDC.e on Polygon held by the **proxy** (this is the Polymarket
    trading balance — what the risk gate actually sees)
  - USDC.e on the **EOA** (any pre-deposit float — usually 0)
  - Native MATIC on the EOA (used for gas)

Implementation: raw JSON-RPC to a public Polygon RPC (no web3.py
dependency). USDC.e is contract 0x2791…, decimals 6. MATIC is the
native asset, returned in wei (10^18).

Failure mode: if Polygon RPC is flaky or rate-limits, the function
returns ``BalanceSnapshot.empty()`` and the frontend renders "—". We
deliberately do not raise — the dashboard should remain useful even
without live balance data.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Public Polygon RPCs — tried in order until one responds. The "official"
# polygon-rpc.com has been intermittently disabled for unkeyed traffic, so
# we keep a fallback list. Override with POLYGON_RPC=... for a private node.
POLYGON_RPC_FALLBACKS = [
    "https://polygon.llamarpc.com",
    "https://polygon.publicnode.com",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
    "https://polygon-rpc.com",
]
_ENV_RPC = os.environ.get("POLYGON_RPC")
POLYGON_RPCS: list[str] = (
    [_ENV_RPC, *POLYGON_RPC_FALLBACKS] if _ENV_RPC else POLYGON_RPC_FALLBACKS
)
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC.e on Polygon (legacy)
USDC_E_DECIMALS = 6
MATIC_DECIMALS = 18

# function selector for balanceOf(address) = keccak256("balanceOf(address)")[:4]
BALANCE_OF_SELECTOR = "0x70a08231"


@dataclass(frozen=True)
class BalanceSnapshot:
    proxy_usdc: float | None
    eoa_usdc: float | None
    eoa_matic: float | None
    proxy_address: str | None
    eoa_address: str | None
    fetched_utc: str

    @classmethod
    def empty(cls) -> BalanceSnapshot:
        return cls(None, None, None, None, None,
                   datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "proxy_usdc": self.proxy_usdc,
            "eoa_usdc": self.eoa_usdc,
            "eoa_matic": self.eoa_matic,
            "proxy_address": self.proxy_address,
            "eoa_address": self.eoa_address,
            "fetched_utc": self.fetched_utc,
        }


def _encoded_balance_call(address: str) -> str:
    """Build the calldata for ``balanceOf(address)`` against the USDC contract."""
    addr = address.lower().removeprefix("0x").zfill(40)
    return BALANCE_OF_SELECTOR + "0" * 24 + addr


def _hex_to_int(h: str) -> int:
    if not isinstance(h, str):
        return 0
    h = h.strip()
    if not h or h == "0x":
        return 0
    return int(h, 16)


def _rpc_call(method: str, params: list, *, timeout: float = 4.0) -> dict | None:
    """Try each fallback RPC in order until one returns a 200 with no
    JSON-RPC ``error`` field. Returns ``None`` if every endpoint fails —
    the dashboard renders "—" in that case rather than crashing."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_err: str | None = None
    with httpx.Client(timeout=timeout) as client:
        for url in POLYGON_RPCS:
            try:
                r = client.post(url, json=body)
            except httpx.HTTPError as e:
                last_err = f"{url}: {e}"
                continue
            if r.status_code != 200:
                last_err = f"{url}: http {r.status_code}"
                continue
            try:
                payload = r.json()
            except ValueError as e:
                last_err = f"{url}: bad json {e}"
                continue
            if isinstance(payload, dict) and payload.get("error"):
                last_err = f"{url}: rpc error {payload['error']}"
                continue
            return payload
    if last_err:
        logger.debug("polygon rpc %s failed across all endpoints: %s", method, last_err)
    return None


def _usdc_balance(address: str) -> float | None:
    body = _rpc_call("eth_call", [
        {"to": USDC_E_ADDRESS, "data": _encoded_balance_call(address)},
        "latest",
    ])
    if body is None or "result" not in body:
        return None
    raw = _hex_to_int(body["result"])
    return raw / (10 ** USDC_E_DECIMALS)


def _native_balance(address: str) -> float | None:
    body = _rpc_call("eth_getBalance", [address, "latest"])
    if body is None or "result" not in body:
        return None
    raw = _hex_to_int(body["result"])
    return raw / (10 ** MATIC_DECIMALS)


def _derive_eoa_from_pk(pk: str) -> str | None:
    """Best-effort: derive the EOA address from POLY_FUNDER_PK if available.

    Uses eth_account (already a transitive dep of py-clob-client). We
    swallow ImportError so the dashboard still loads if eth_account is
    not installed in the active venv.
    """
    try:
        from eth_account import Account  # type: ignore
    except ImportError:                                       # pragma: no cover
        return None
    try:
        return Account.from_key(pk).address
    except (ValueError, TypeError):
        return None


def fetch_balances() -> BalanceSnapshot:
    """One-shot balance fetch. Reads addresses from environment vars
    populated by ``.env`` (loaded into ``os.environ`` by the FastAPI
    app's startup hook)."""
    proxy = os.environ.get("POLY_PROXY_ADDRESS") or None
    pk = os.environ.get("POLY_FUNDER_PK") or None
    eoa = _derive_eoa_from_pk(pk) if pk else None

    proxy_usdc = _usdc_balance(proxy) if proxy else None
    eoa_usdc = _usdc_balance(eoa) if eoa else None
    eoa_matic = _native_balance(eoa) if eoa else None

    return BalanceSnapshot(
        proxy_usdc=proxy_usdc,
        eoa_usdc=eoa_usdc,
        eoa_matic=eoa_matic,
        proxy_address=proxy,
        eoa_address=eoa,
        fetched_utc=datetime.now(timezone.utc).isoformat(),
    )
