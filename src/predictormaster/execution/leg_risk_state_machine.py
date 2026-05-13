"""Leg-risk state machine — handle one-sided fills on paired arbs.

The premise. An intra-Polymarket arb is two legs: BUY YES at p_YES,
BUY NO at p_NO, with edge ε = 1 - p_YES - p_NO - fees. Both legs must
fill for the edge to crystallise. If one fills and the other doesn't,
we hold a directional position we never wanted.

Decision tree on a one-sided fill (Leg A filled, Leg B failed)
--------------------------------------------------------------
Three options:

  1. SCRATCH: sell the filled position back into the book at the
     opposite side. Locks in spread loss; bounded and immediate.
     Loss ≈ s · (p_A - bid_A_now) per share.

  2. HEDGE: retry the failed leg at the NEW market price. If the
     market moved away, this may still be profitable but with
     reduced edge. Locks in s · (1 - p_A - p_B_new - fees) per
     share, which can be negative.

  3. HOLD: keep the position. Speculative — equivalent to taking a
     directional bet at p_A. Only rational if we have a separate
     view on the underlying outcome. For arb α2, NEVER appropriate.

Decision rule (this module's policy)
------------------------------------
We always pick min loss between SCRATCH and HEDGE. HOLD is never an
option — it would convert α2 from a structural arb into a directional
bet, which violates the strategy contract.

  expected_scratch_loss = s · (p_A_fill - bid_A_now)               [≥ 0]
  expected_hedge_loss   = s · (p_A_fill + ask_B_now + 2·fee - 1)   [can be ±]

  if expected_hedge_loss < expected_scratch_loss:
      HEDGE  (retry leg B at new market)
  else:
      SCRATCH (sell A back, eat the spread)

The state machine guarantees:
  - At most one HEDGE attempt before forcing a SCRATCH (no infinite
    retry on a moving market).
  - SCRATCH orders are IOC at the best opposing bid; if they fail
    we escalate to MARKET (cross the spread by 1 tick).
  - Every state transition is journalled with a monotonic timestamp.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from .async_gateway import AsyncPolymarketGateway, PairedDispatch
from .polymarket_clob import OrderBook, OrderRequest

logger = logging.getLogger(__name__)

POLY_TAKER_FEE = 0.02


class LegState(Enum):
    IDLE = "idle"
    DISPATCHING = "dispatching"
    BOTH_FILLED = "both_filled"          # success
    ONE_SIDED = "one_sided"               # leg A or B but not both
    HEDGING = "hedging"                   # retrying the failed leg
    SCRATCHING = "scratching"             # closing the lone leg
    FLAT = "flat"                         # closed, P&L crystallised
    ABANDONED = "abandoned"               # gave up; manual review needed


@dataclass(frozen=True)
class LegFill:
    side: str               # "BUY"
    token_id: str
    requested_price: float
    requested_size: float
    fill_price: float
    fill_size: float
    order_id: str | None
    ts_ns: int


@dataclass
class ArbPosition:
    """Tracks an in-flight paired arb. Mutates as the state machine runs."""
    arb_id: str
    expected_edge: float
    state: LegState = LegState.IDLE
    filled_leg: LegFill | None = None
    missing_leg_req: OrderRequest | None = None
    hedge_attempts: int = 0
    max_hedge_attempts: int = 1
    realised_pnl_per_share: float | None = None
    history: list[tuple[float, LegState, str]] = field(default_factory=list)

    def transition(self, new_state: LegState, note: str = "") -> None:
        ts = time.perf_counter()
        self.history.append((ts, new_state, note))
        self.state = new_state


class BookFetcher(Protocol):
    """Anything that can produce a current OrderBook for a token. The
    gateway implements this naturally; tests inject a stub."""
    async def get_book(self, token_id: str) -> OrderBook: ...


@dataclass
class HedgePolicy:
    """Numerical parameters for the scratch-vs-hedge decision.

    Defaults are tuned conservatively for the nano-live $15 stage:
    we'd rather take a known small loss than chase an evaporating
    edge on a moving market.
    """
    fee_per_leg: float = POLY_TAKER_FEE
    max_hedge_attempts: int = 1
    scratch_tick_slippage: float = 0.001    # 1 tick worse than top-bid when
                                            # forcing the scratch through
    abandon_if_book_empty: bool = True      # if no opposite side, give up
                                            # rather than rest a GTC
    decision_log_level: int = logging.INFO


def _scratch_loss(filled: LegFill, book: OrderBook,
                  tick_slippage: float) -> tuple[float, float]:
    """Compute scratch loss per share + the price we'd actually use.

    Returns ``(loss_per_share, scratch_price)``. ``loss_per_share`` is
    the dollar loss per unit position (positive number).
    """
    # We're long YES at filled.requested_price; to scratch, we SELL
    # back into the bids.
    if not book.bids:
        return (float("inf"), 0.0)
    top_bid = book.bids[0].price
    scratch_px = max(0.0, top_bid - tick_slippage)
    loss_per_share = filled.fill_price - scratch_px
    return (loss_per_share, scratch_px)


def _hedge_loss(filled: LegFill, missing_req: OrderRequest, book_b: OrderBook,
                fee_per_leg: float) -> tuple[float, float]:
    """Compute hedge loss per share + the price we'd actually pay.

    The hedge is BUY of the OTHER outcome (NO if A was YES). New cost
    = filled.fill_price + book_b.top_ask + 2·fee. Loss = cost - 1.
    """
    if not book_b.asks:
        return (float("inf"), 0.0)
    new_ask = book_b.asks[0].price
    # Each share of YES + each share of NO redeems to $1 at resolution.
    cost = filled.fill_price + new_ask + 2.0 * fee_per_leg
    loss_per_share = cost - 1.0    # negative = profit; positive = loss
    return (loss_per_share, new_ask)


@dataclass
class LegRiskStateMachine:
    """Drives a single ArbPosition from dispatch through to FLAT.

    Use one instance per in-flight arb. The instance is stateful and
    not re-entrant. To run many arbs concurrently, instantiate many
    state machines and let asyncio schedule them.
    """
    gateway: AsyncPolymarketGateway
    book_fetcher: BookFetcher
    policy: HedgePolicy = field(default_factory=HedgePolicy)

    async def run(
        self,
        arb_id: str,
        expected_edge: float,
        leg_a_req: OrderRequest,
        leg_b_req: OrderRequest,
    ) -> ArbPosition:
        """Execute the full state-machine pass for one arb.

        Returns the final ArbPosition with state ∈ {BOTH_FILLED, FLAT,
        ABANDONED}. Inspect ``.realised_pnl_per_share`` and ``.history``
        for post-trade analysis.
        """
        pos = ArbPosition(
            arb_id=arb_id, expected_edge=expected_edge,
            max_hedge_attempts=self.policy.max_hedge_attempts,
        )
        pos.transition(LegState.DISPATCHING, "paired dispatch starting")

        result = await self.gateway.dispatch_paired(leg_a_req, leg_b_req)
        self._classify(pos, result, leg_a_req, leg_b_req)

        if pos.state is LegState.BOTH_FILLED:
            pos.realised_pnl_per_share = expected_edge
            return pos
        if pos.state is LegState.ABANDONED:
            return pos

        # ONE_SIDED — run the scratch/hedge decision.
        await self._handle_one_sided(pos)
        return pos

    # ---------------- internals ----------------

    def _classify(self, pos: ArbPosition, dispatch: PairedDispatch,
                  req_a: OrderRequest, req_b: OrderRequest) -> None:
        a = dispatch.leg_a
        b = dispatch.leg_b
        a_ok = a.result is not None and a.result.accepted
        b_ok = b.result is not None and b.result.accepted

        if a_ok and b_ok:
            pos.transition(LegState.BOTH_FILLED,
                           f"skew={dispatch.inter_leg_skew_ns}ns "
                           f"total={dispatch.total_elapsed_ns}ns")
            return

        if not a_ok and not b_ok:
            # Both failed → no exposure → cleanly abandon.
            pos.transition(LegState.ABANDONED,
                           f"both legs rejected (a={a.error or 'rejected'}, "
                           f"b={b.error or 'rejected'})")
            return

        # Exactly one accepted. Capture the filled leg.
        if a_ok:
            assert a.result is not None
            pos.filled_leg = LegFill(
                side=req_a.side, token_id=req_a.token_id,
                requested_price=req_a.price, requested_size=req_a.size,
                fill_price=a.result.avg_fill_price,
                fill_size=a.result.filled_size,
                order_id=a.result.order_id, ts_ns=a.response_ts_ns,
            )
            pos.missing_leg_req = req_b
        else:
            assert b.result is not None
            pos.filled_leg = LegFill(
                side=req_b.side, token_id=req_b.token_id,
                requested_price=req_b.price, requested_size=req_b.size,
                fill_price=b.result.avg_fill_price,
                fill_size=b.result.filled_size,
                order_id=b.result.order_id, ts_ns=b.response_ts_ns,
            )
            pos.missing_leg_req = req_a
        pos.transition(LegState.ONE_SIDED,
                       f"filled={pos.filled_leg.token_id}, "
                       f"missing={pos.missing_leg_req.token_id}")

    async def _handle_one_sided(self, pos: ArbPosition) -> None:
        """Decide scratch vs. hedge using current market state."""
        assert pos.filled_leg is not None
        assert pos.missing_leg_req is not None

        # Fetch current state of BOTH books (we need the filled leg's
        # bids for scratch, the missing leg's asks for hedge).
        book_filled = await self.book_fetcher.get_book(pos.filled_leg.token_id)
        book_missing = await self.book_fetcher.get_book(pos.missing_leg_req.token_id)

        scratch_loss, scratch_px = _scratch_loss(
            pos.filled_leg, book_filled, self.policy.scratch_tick_slippage,
        )
        hedge_loss, hedge_px = _hedge_loss(
            pos.filled_leg, pos.missing_leg_req, book_missing,
            self.policy.fee_per_leg,
        )

        logger.log(
            self.policy.decision_log_level,
            "[%s] one-sided fill — scratch=$%.4f/share @ %.4f, "
            "hedge=$%.4f/share @ %.4f",
            pos.arb_id, scratch_loss, scratch_px, hedge_loss, hedge_px,
        )

        # Both options unavailable → abandon. Operator must close manually.
        if not (scratch_loss < float("inf") or hedge_loss < float("inf")):
            pos.transition(LegState.ABANDONED, "both books empty on close attempt")
            return

        # Pick the cheaper option (smaller loss = larger -loss).
        # Note: hedge_loss can be negative (still profitable arb).
        if hedge_loss < scratch_loss and pos.hedge_attempts < pos.max_hedge_attempts:
            await self._try_hedge(pos, hedge_px, book_missing)
            return
        await self._try_scratch(pos, scratch_px)

    async def _try_hedge(self, pos: ArbPosition, new_price: float,
                         _book: OrderBook) -> None:
        assert pos.missing_leg_req is not None
        pos.transition(LegState.HEDGING,
                       f"retry leg at new price {new_price:.4f}")
        pos.hedge_attempts += 1
        retry_req = OrderRequest(
            token_id=pos.missing_leg_req.token_id,
            side=pos.missing_leg_req.side,
            price=new_price,
            size=pos.missing_leg_req.size,
            order_type="IOC",
            client_order_id=f"{pos.arb_id}-hedge-{pos.hedge_attempts}",
        )
        timed = await self.gateway._submit_one(retry_req)    # noqa: SLF001
        if timed.result is not None and timed.result.accepted:
            assert pos.filled_leg is not None
            pos.realised_pnl_per_share = (
                1.0 - pos.filled_leg.fill_price - new_price
                - 2.0 * self.policy.fee_per_leg
            )
            pos.transition(LegState.FLAT,
                           f"hedge filled, pnl/share={pos.realised_pnl_per_share:+.4f}")
            return
        # Hedge failed — escalate to scratch.
        logger.warning("[%s] hedge attempt %d failed: %s",
                       pos.arb_id, pos.hedge_attempts,
                       timed.error or "rejected")
        book = await self.book_fetcher.get_book(pos.filled_leg.token_id)  # type: ignore[union-attr]
        scratch_loss, scratch_px = _scratch_loss(
            pos.filled_leg, book, self.policy.scratch_tick_slippage,  # type: ignore[arg-type]
        )
        if scratch_loss == float("inf"):
            pos.transition(LegState.ABANDONED,
                           "hedge failed AND scratch book empty")
            return
        await self._try_scratch(pos, scratch_px)

    async def _try_scratch(self, pos: ArbPosition, scratch_px: float) -> None:
        assert pos.filled_leg is not None
        pos.transition(LegState.SCRATCHING,
                       f"sell back at {scratch_px:.4f}")
        scratch_req = OrderRequest(
            token_id=pos.filled_leg.token_id,
            side="SELL",
            price=scratch_px,
            size=pos.filled_leg.fill_size,
            order_type="IOC",
            client_order_id=f"{pos.arb_id}-scratch",
        )
        timed = await self.gateway._submit_one(scratch_req)    # noqa: SLF001
        if timed.result is not None and timed.result.accepted:
            pos.realised_pnl_per_share = (
                scratch_px - pos.filled_leg.fill_price
                - self.policy.fee_per_leg
            )
            pos.transition(LegState.FLAT,
                           f"scratched, pnl/share={pos.realised_pnl_per_share:+.4f}")
            return
        # Scratch IOC failed — book moved away. Escalate to crossing-spread MARKET.
        logger.warning("[%s] scratch IOC failed: %s — escalating to MARKET",
                       pos.arb_id, timed.error or "rejected")
        market_req = OrderRequest(
            token_id=pos.filled_leg.token_id,
            side="SELL",
            price=max(0.001, scratch_px - 0.01),    # cross by 1¢
            size=pos.filled_leg.fill_size,
            order_type="MARKET",
            client_order_id=f"{pos.arb_id}-scratch-mkt",
        )
        timed2 = await self.gateway._submit_one(market_req)    # noqa: SLF001
        if timed2.result is not None and timed2.result.accepted:
            pos.realised_pnl_per_share = (
                timed2.result.avg_fill_price - pos.filled_leg.fill_price
                - self.policy.fee_per_leg
            )
            pos.transition(
                LegState.FLAT,
                f"market-scratched at {timed2.result.avg_fill_price:.4f}, "
                f"pnl/share={pos.realised_pnl_per_share:+.4f}",
            )
            return
        pos.transition(LegState.ABANDONED,
                       f"BOTH scratch attempts failed — manual flatten required: {timed2.error}")


# ---------------- post-trade analytics ----------------

@dataclass(frozen=True)
class ArbExecutionStats:
    """Summary metrics for a batch of finished ArbPositions.

    The two numbers that matter for sizing future trades:
      - ``one_sided_fill_rate`` — fraction of arbs that needed
        scratch/hedge. Sets the safety margin you need above the raw
        arb edge before firing.
      - ``avg_slippage_vs_expected`` — mean of (realised_pnl - expected_edge)
        per share. Should be small and negative; large negative means
        execution is killing the strategy.
    """
    n_arbs: int
    n_both_filled: int
    n_hedged: int
    n_scratched: int
    n_abandoned: int
    one_sided_fill_rate: float
    avg_realised_pnl_per_share: float
    avg_slippage_vs_expected: float
    ts_utc: datetime


def summarise(positions: list[ArbPosition]) -> ArbExecutionStats:
    if not positions:
        return ArbExecutionStats(
            n_arbs=0, n_both_filled=0, n_hedged=0, n_scratched=0,
            n_abandoned=0, one_sided_fill_rate=0.0,
            avg_realised_pnl_per_share=0.0, avg_slippage_vs_expected=0.0,
            ts_utc=datetime.now(timezone.utc),
        )
    both = sum(1 for p in positions if p.state is LegState.BOTH_FILLED)
    hedged = sum(1 for p in positions
                 if any(s is LegState.HEDGING for _, s, _ in p.history))
    scratched = sum(1 for p in positions
                    if any(s is LegState.SCRATCHING for _, s, _ in p.history))
    abandoned = sum(1 for p in positions if p.state is LegState.ABANDONED)
    one_sided = sum(1 for p in positions
                    if any(s is LegState.ONE_SIDED for _, s, _ in p.history))
    realised = [p.realised_pnl_per_share for p in positions
                if p.realised_pnl_per_share is not None]
    slip = [p.realised_pnl_per_share - p.expected_edge for p in positions
            if p.realised_pnl_per_share is not None]
    return ArbExecutionStats(
        n_arbs=len(positions),
        n_both_filled=both,
        n_hedged=hedged,
        n_scratched=scratched,
        n_abandoned=abandoned,
        one_sided_fill_rate=one_sided / len(positions),
        avg_realised_pnl_per_share=sum(realised) / len(realised) if realised else 0.0,
        avg_slippage_vs_expected=sum(slip) / len(slip) if slip else 0.0,
        ts_utc=datetime.now(timezone.utc),
    )
