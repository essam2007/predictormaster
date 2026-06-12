"""Async execution gateway — concurrent paired-leg dispatch.

The arb edge ε = 1 - Ask_YES - Ask_NO - 2·fee evaporates with the
square-root of inter-leg time: E[leakage] ≈ σ_p · √Δt. With Polymarket
REST, the sequential floor is 2·RTT ≈ 100ms. Concurrent ``asyncio.gather``
collapses that to 1·RTT + scheduler_skew ≈ 50ms + <1ms.

Production tuning levers (in order of latency payoff)
-----------------------------------------------------
1. Connection reuse via a long-lived ``httpx.AsyncClient`` (saves TLS
   handshake ≈ 30-80ms per call).
2. HTTP/2 multiplexing (single TCP connection, parallel streams).
3. DNS pre-resolve via ``socket.getaddrinfo`` warm-up at boot.
4. uvloop (drop-in event-loop replacement, ~2× faster than the asyncio
   stdlib loop on macOS/Linux).
5. TLS resumption tickets (the default in httpx; just don't disable).
6. ``TCP_NODELAY`` (httpx sets this; verify under load).

What this does NOT do (path to lower latency)
---------------------------------------------
- No FPGA / kernel-bypass NIC. Polymarket runs a REST relayer on
  AWS — the dominant latency is wire + relayer queue, not our stack.
- No colocation. Polymarket doesn't offer it.
- No binary protocol. PM's matching engine is JSON over HTTPS.

If/when Polymarket exposes a WebSocket order-entry channel (currently
read-only WS exists for book updates), the C++ critical-path lives in
a separate process consuming the WS feed via lock-free SPSC ring
buffer and emitting signed orders. That's tractable; FPGA is not.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .polymarket_clob import (
    OrderBook,
    OrderRequest,
    OrderResult,
    _parse_book,
)

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"


@dataclass(frozen=True)
class TimedResult:
    """One leg's outcome plus wall-clock latency components."""
    result: OrderResult | None
    error: str | None
    dispatch_ts_ns: int       # perf_counter_ns at .gather() entry
    response_ts_ns: int       # perf_counter_ns at response received
    latency_ns: int           # response - dispatch

    @property
    def latency_ms(self) -> float:
        return self.latency_ns / 1_000_000.0


@dataclass(frozen=True)
class PairedDispatch:
    """Result of dispatching two legs concurrently."""
    leg_a: TimedResult
    leg_b: TimedResult
    inter_leg_skew_ns: int    # |a.dispatch_ts - b.dispatch_ts|
    total_elapsed_ns: int     # max(a.response_ts, b.response_ts) - min(dispatch_ts)
    ts_utc: datetime

    @property
    def both_accepted(self) -> bool:
        return (
            self.leg_a.result is not None
            and self.leg_a.result.accepted
            and self.leg_b.result is not None
            and self.leg_b.result.accepted
        )

    @property
    def one_sided(self) -> bool:
        a_ok = self.leg_a.result is not None and self.leg_a.result.accepted
        b_ok = self.leg_b.result is not None and self.leg_b.result.accepted
        return a_ok != b_ok    # exactly one accepted


@dataclass
class AsyncPolymarketGateway:
    """Connection-pooled async client for the Polymarket CLOB.

    ``base_url`` and ``signer`` are kept separate so the same gateway
    can serve read-only (no creds) and signing flows. Construct one
    instance per process and reuse — every new client costs a TLS
    handshake.
    """
    base_url: str = CLOB_BASE
    timeout_s: float = 5.0
    max_keepalive: int = 16
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _signer = None  # py_clob_client.client.ClobClient | None — lazy

    async def __aenter__(self) -> AsyncPolymarketGateway:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            http2=True,
            timeout=self.timeout_s,
            limits=httpx.Limits(
                max_keepalive_connections=self.max_keepalive,
                max_connections=self.max_keepalive,
                keepalive_expiry=60.0,
            ),
            headers={"User-Agent": "predictormaster/0.1 async-gateway"},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------------- Read-only ----------------

    async def get_book(self, token_id: str) -> OrderBook:
        """Fetch one book. Use ``gather_books`` for multiple."""
        assert self._client is not None, "use 'async with' to open the gateway"
        r = await self._client.get("/book", params={"token_id": token_id})
        r.raise_for_status()
        return _parse_book(r.json())

    async def gather_books(self, token_ids: Sequence[str]) -> list[OrderBook]:
        """Fetch N books concurrently. Returns in input order."""
        assert self._client is not None
        coros = [self._client.get("/book", params={"token_id": t}) for t in token_ids]
        responses = await asyncio.gather(*coros, return_exceptions=True)
        out: list[OrderBook] = []
        for tid, resp in zip(token_ids, responses, strict=True):
            if isinstance(resp, Exception):
                logger.warning("book fetch failed for %s: %r", tid, resp)
                out.append(_parse_book({"market": tid, "bids": [], "asks": []}))
                continue
            try:
                resp.raise_for_status()
                out.append(_parse_book(resp.json()))
            except (httpx.HTTPStatusError, ValueError) as e:
                logger.warning("book parse failed for %s: %r", tid, e)
                out.append(_parse_book({"market": tid, "bids": [], "asks": []}))
        return out

    # ---------------- Write — paired dispatch ----------------

    def _ensure_signer(self):
        """Lazy-import + cache py_clob_client. Raises if creds missing."""
        if self._signer is not None:
            return self._signer
        required = ("POLY_API_KEY", "POLY_API_SECRET", "POLY_API_PASSPHRASE",
                    "POLY_PROXY_ADDRESS", "POLY_FUNDER_PK")
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"missing POLY_* env: {', '.join(missing)}")
        from py_clob_client.client import ClobClient
        self._signer = ClobClient(
            host=self.base_url,
            chain_id=137,
            key=os.environ["POLY_FUNDER_PK"],
            funder=os.environ["POLY_PROXY_ADDRESS"],
            creds={
                "key": os.environ["POLY_API_KEY"],
                "secret": os.environ["POLY_API_SECRET"],
                "passphrase": os.environ["POLY_API_PASSPHRASE"],
            },
        )
        return self._signer

    async def _submit_one(self, req: OrderRequest) -> TimedResult:
        """Sign locally, POST async. EIP-712 signing is CPU-bound (~1ms)
        so we run it on the event-loop executor to avoid blocking."""
        dispatch_ns = time.perf_counter_ns()
        try:
            signer = self._ensure_signer()
            from py_clob_client.clob_types import OrderArgs
            loop = asyncio.get_running_loop()
            # Signing is CPU-bound; off-load to default executor.
            order = await loop.run_in_executor(
                None,
                lambda: signer.create_order(OrderArgs(
                    token_id=req.token_id, price=req.price,
                    size=req.size, side=req.side,
                )),
            )
            # py_clob_client.post_order is sync requests under the hood.
            resp = await loop.run_in_executor(
                None, lambda: signer.post_order(order, req.order_type)
            )
            response_ns = time.perf_counter_ns()
            return TimedResult(
                result=OrderResult(
                    accepted=bool(resp.get("success")),
                    order_id=resp.get("orderID"),
                    filled_size=float(resp.get("makingAmount", 0) or 0),
                    avg_fill_price=req.price,
                    raw=resp,
                    error=None if resp.get("success") else str(resp.get("errorMsg", "rejected")),
                ),
                error=None,
                dispatch_ts_ns=dispatch_ns,
                response_ts_ns=response_ns,
                latency_ns=response_ns - dispatch_ns,
            )
        except Exception as e:    # noqa: BLE001 — surface raw exception to caller
            response_ns = time.perf_counter_ns()
            logger.exception("submit failed for %s", req.token_id)
            return TimedResult(
                result=None,
                error=repr(e),
                dispatch_ts_ns=dispatch_ns,
                response_ts_ns=response_ns,
                latency_ns=response_ns - dispatch_ns,
            )

    async def dispatch_paired(
        self,
        req_a: OrderRequest,
        req_b: OrderRequest,
    ) -> PairedDispatch:
        """Submit two orders concurrently. Returns once both terminate.

        Both coros are scheduled on the same event-loop tick via
        ``asyncio.gather``. The inter-leg dispatch skew is observable
        in the result for post-trade analysis.
        """
        loop_start = time.perf_counter_ns()
        leg_a, leg_b = await asyncio.gather(
            self._submit_one(req_a),
            self._submit_one(req_b),
        )
        loop_end = time.perf_counter_ns()
        skew = abs(leg_a.dispatch_ts_ns - leg_b.dispatch_ts_ns)
        total = loop_end - loop_start
        return PairedDispatch(
            leg_a=leg_a, leg_b=leg_b,
            inter_leg_skew_ns=skew,
            total_elapsed_ns=total,
            ts_utc=datetime.now(timezone.utc),
        )

    # ---------------- Cancellation (used by hedging logic) ----------------

    async def cancel_order(self, order_id: str) -> bool:
        """Best-effort cancel. Returns True if PM accepted the cancel."""
        try:
            signer = self._ensure_signer()
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: signer.cancel(order_id=order_id))
            return bool(resp.get("success", False))
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel failed for %s: %r", order_id, e)
            return False


async def prewarm_dns_and_pool(gateway: AsyncPolymarketGateway,
                               sample_token: str | None = None) -> None:
    """Eliminate the cold-start latency penalty.

    On the first request, the client pays:
      - DNS resolution (~10-40ms on cold cache)
      - TLS 1.3 handshake (~30ms for 1-RTT, 0ms for 0-RTT resumption)
      - HTTP/2 SETTINGS exchange (~1 RTT)

    Running one warm-up call at process start moves all of this off
    the critical path. Use ``sample_token=None`` to skip the book
    fetch and only warm DNS+TLS+H2.
    """
    assert gateway._client is not None
    try:
        if sample_token is not None:
            await gateway.get_book(sample_token)
        else:
            # /time is light, always returns 200, perfect warm-up endpoint
            await gateway._client.get("/")
    except Exception as e:  # noqa: BLE001
        logger.warning("prewarm: %r", e)
