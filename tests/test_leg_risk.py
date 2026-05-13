"""Tests for the leg-risk state machine and async gateway plumbing.

Integration tests for the async gateway are deliberately omitted —
they'd require either a live Polymarket account or a mocked HTTPS
server. Unit tests cover the state-machine logic exhaustively against
stubbed gateway and book fetchers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from predictormaster.execution.async_gateway import (
    PairedDispatch,
    TimedResult,
)
from predictormaster.execution.leg_risk_state_machine import (
    HedgePolicy,
    LegRiskStateMachine,
    LegState,
    _hedge_loss,
    _scratch_loss,
    summarise,
)
from predictormaster.execution.polymarket_clob import (
    BookLevel,
    OrderBook,
    OrderRequest,
    OrderResult,
)


def _book(bids=(), asks=(), tid="t"):
    return OrderBook(
        token_id=tid,
        bids=tuple(BookLevel(p, s) for p, s in bids),
        asks=tuple(BookLevel(p, s) for p, s in asks),
        fetched_utc=datetime.now(timezone.utc),
    )


def _ok_result(price=0.45, size=10, oid="ord-1"):
    return OrderResult(accepted=True, order_id=oid, filled_size=size,
                       avg_fill_price=price, raw={"success": True})


def _bad_result(err="rejected"):
    return OrderResult(accepted=False, order_id=None, filled_size=0,
                       avg_fill_price=0.0, raw={}, error=err)


def _timed(result):
    return TimedResult(result=result, error=None,
                       dispatch_ts_ns=0, response_ts_ns=1_000_000,
                       latency_ns=1_000_000)


def _paired(leg_a_result, leg_b_result):
    return PairedDispatch(
        leg_a=_timed(leg_a_result), leg_b=_timed(leg_b_result),
        inter_leg_skew_ns=100, total_elapsed_ns=2_000_000,
        ts_utc=datetime.now(timezone.utc),
    )


# ---------------- Stubs ----------------

@dataclass
class StubGateway:
    """Records calls and returns scripted outcomes."""
    paired_outcomes: list[PairedDispatch] = field(default_factory=list)
    submit_outcomes: list[TimedResult] = field(default_factory=list)
    submit_calls: list[OrderRequest] = field(default_factory=list)

    async def dispatch_paired(self, _a, _b):
        return self.paired_outcomes.pop(0)

    async def _submit_one(self, req):
        self.submit_calls.append(req)
        if not self.submit_outcomes:
            return _timed(_bad_result("no more scripted outcomes"))
        return self.submit_outcomes.pop(0)


@dataclass
class StubFetcher:
    books: dict[str, OrderBook] = field(default_factory=dict)

    async def get_book(self, token_id: str) -> OrderBook:
        return self.books.get(token_id, _book(tid=token_id))


# ---------------- _scratch_loss / _hedge_loss ----------------

def test_scratch_loss_uses_top_bid_minus_tick():
    filled_leg = type("F", (), dict(
        side="BUY", token_id="t", requested_price=0.45,
        requested_size=10, fill_price=0.45, fill_size=10,
        order_id="o", ts_ns=0,
    ))()
    book = _book(bids=[(0.44, 100), (0.43, 50)])
    loss, px = _scratch_loss(filled_leg, book, tick_slippage=0.001)
    # filled at 0.45, scratch at 0.44 - 0.001 = 0.439 → loss = 0.011 per share
    assert px == pytest.approx(0.439)
    assert loss == pytest.approx(0.011)


def test_scratch_loss_inf_when_no_bids():
    filled_leg = type("F", (), dict(fill_price=0.45))()
    loss, _ = _scratch_loss(filled_leg, _book(bids=[]), tick_slippage=0.001)
    assert loss == float("inf")


def test_hedge_loss_can_be_negative_when_arb_still_alive():
    filled_leg = type("F", (), dict(fill_price=0.45))()
    missing_req = OrderRequest(token_id="nt", side="BUY", price=0.45, size=10)
    book_b = _book(asks=[(0.48, 100)])
    # cost = 0.45 + 0.48 + 2·0.02 = 0.97 → loss = -0.03 (i.e. +0.03 profit)
    loss, px = _hedge_loss(filled_leg, missing_req, book_b, fee_per_leg=0.02)
    assert px == 0.48
    assert loss == pytest.approx(-0.03)


def test_hedge_loss_positive_when_market_moved():
    filled_leg = type("F", (), dict(fill_price=0.45))()
    missing_req = OrderRequest(token_id="nt", side="BUY", price=0.45, size=10)
    book_b = _book(asks=[(0.65, 100)])    # market ran away
    loss, _ = _hedge_loss(filled_leg, missing_req, book_b, fee_per_leg=0.02)
    # cost = 0.45 + 0.65 + 0.04 = 1.14 → loss = +0.14
    assert loss == pytest.approx(0.14)


# ---------------- State machine ----------------

def test_state_machine_both_filled_no_intervention():
    gw = StubGateway(paired_outcomes=[_paired(_ok_result(), _ok_result())])
    fetcher = StubFetcher()
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher)

    pos = asyncio.run(sm.run(
        arb_id="arb-1",
        expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45,
                               size=10, order_type="IOC"),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45,
                               size=10, order_type="IOC"),
    ))
    assert pos.state is LegState.BOTH_FILLED
    assert pos.realised_pnl_per_share == 0.05
    # Pristine: no scratch/hedge orders sent.
    assert gw.submit_calls == []


def test_state_machine_both_failed_abandons():
    gw = StubGateway(paired_outcomes=[_paired(_bad_result(), _bad_result())])
    fetcher = StubFetcher()
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher)

    pos = asyncio.run(sm.run(
        arb_id="arb-2", expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45, size=10),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45, size=10),
    ))
    assert pos.state is LegState.ABANDONED
    assert pos.realised_pnl_per_share is None    # never had exposure
    assert gw.submit_calls == []                 # nothing to flatten


def test_one_sided_hedges_when_market_is_friendly():
    """Leg A fills at 0.45; Leg B fails. Missing-leg ask is still 0.48
    so hedge_loss = -0.03 (still profitable). Should pick HEDGE, and
    the hedge succeeds."""
    gw = StubGateway(
        paired_outcomes=[_paired(_ok_result(price=0.45), _bad_result())],
        # Hedge retry on Leg B succeeds at 0.48.
        submit_outcomes=[_timed(_ok_result(price=0.48, oid="hedge-1"))],
    )
    fetcher = StubFetcher(books={
        "yt": _book(bids=[(0.44, 100)]),       # for scratch alt: 0.439, loss 0.011
        "nt": _book(asks=[(0.48, 100)]),       # for hedge:        loss -0.03
    })
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher)

    pos = asyncio.run(sm.run(
        arb_id="arb-3", expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45, size=10),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45, size=10),
    ))
    assert pos.state is LegState.FLAT
    assert pos.hedge_attempts == 1
    assert pos.realised_pnl_per_share == pytest.approx(0.03)
    # Confirms we tried the hedge, not the scratch.
    assert len(gw.submit_calls) == 1
    assert gw.submit_calls[0].token_id == "nt"
    assert gw.submit_calls[0].side == "BUY"


def test_one_sided_scratches_when_market_ran_away():
    """Leg A fills at 0.45; Leg B fails. Missing-leg ask ran to 0.70,
    hedge_loss = +0.20. Scratch from bid 0.44 → loss 0.011. Should
    pick SCRATCH (smaller loss)."""
    gw = StubGateway(
        paired_outcomes=[_paired(_ok_result(price=0.45), _bad_result())],
        submit_outcomes=[_timed(_ok_result(price=0.439, oid="scratch-1"))],
    )
    fetcher = StubFetcher(books={
        "yt": _book(bids=[(0.44, 100)]),
        "nt": _book(asks=[(0.70, 100)]),
    })
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher)

    pos = asyncio.run(sm.run(
        arb_id="arb-4", expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45, size=10),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45, size=10),
    ))
    assert pos.state is LegState.FLAT
    assert pos.hedge_attempts == 0           # never hedged
    assert pos.realised_pnl_per_share is not None
    # pnl = scratch_px - fill_price - fee = 0.439 - 0.45 - 0.02 = -0.031
    assert pos.realised_pnl_per_share == pytest.approx(-0.031)
    assert len(gw.submit_calls) == 1
    assert gw.submit_calls[0].side == "SELL"
    assert gw.submit_calls[0].order_type == "IOC"


def test_failed_hedge_escalates_to_scratch():
    """Hedge looks attractive but the retry order itself fails. The
    machine must fall back to scratching the original filled leg."""
    gw = StubGateway(
        paired_outcomes=[_paired(_ok_result(price=0.45), _bad_result())],
        submit_outcomes=[
            _timed(_bad_result("hedge IOC missed")),
            _timed(_ok_result(price=0.439, oid="scratch-after-hedge")),
        ],
    )
    fetcher = StubFetcher(books={
        "yt": _book(bids=[(0.44, 100)]),
        "nt": _book(asks=[(0.48, 100)]),    # hedge looks good
    })
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher)

    pos = asyncio.run(sm.run(
        arb_id="arb-5", expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45, size=10),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45, size=10),
    ))
    assert pos.state is LegState.FLAT
    assert pos.hedge_attempts == 1
    assert pos.realised_pnl_per_share == pytest.approx(-0.031)
    # Two attempts: hedge (failed), then scratch (succeeded).
    assert len(gw.submit_calls) == 2


def test_summarise_counts_states_correctly():
    """Aggregate stats across a batch of finished positions."""
    from predictormaster.execution.leg_risk_state_machine import ArbPosition

    p1 = ArbPosition(arb_id="a1", expected_edge=0.05, state=LegState.BOTH_FILLED,
                     realised_pnl_per_share=0.05)
    p2 = ArbPosition(arb_id="a2", expected_edge=0.03, state=LegState.FLAT,
                     realised_pnl_per_share=-0.01)
    p2.history = [(0.0, LegState.ONE_SIDED, ""), (0.1, LegState.SCRATCHING, "")]
    p3 = ArbPosition(arb_id="a3", expected_edge=0.04, state=LegState.ABANDONED)
    stats = summarise([p1, p2, p3])
    assert stats.n_arbs == 3
    assert stats.n_both_filled == 1
    assert stats.n_scratched == 1
    assert stats.n_abandoned == 1
    assert stats.one_sided_fill_rate == pytest.approx(1/3)
    # Avg realised PnL across the two that crystallised
    assert stats.avg_realised_pnl_per_share == pytest.approx((0.05 - 0.01) / 2)


# ---------------- HedgePolicy ----------------

def test_hedge_policy_max_attempts_respected():
    """max_hedge_attempts=0 means we always scratch, never hedge."""
    policy = HedgePolicy(max_hedge_attempts=0)
    gw = StubGateway(
        paired_outcomes=[_paired(_ok_result(price=0.45), _bad_result())],
        submit_outcomes=[_timed(_ok_result(price=0.439, oid="scratch-only"))],
    )
    fetcher = StubFetcher(books={
        "yt": _book(bids=[(0.44, 100)]),
        "nt": _book(asks=[(0.48, 100)]),    # hedge looks good but disallowed
    })
    sm = LegRiskStateMachine(gateway=gw, book_fetcher=fetcher, policy=policy)
    pos = asyncio.run(sm.run(
        arb_id="arb-6", expected_edge=0.05,
        leg_a_req=OrderRequest(token_id="yt", side="BUY", price=0.45, size=10),
        leg_b_req=OrderRequest(token_id="nt", side="BUY", price=0.45, size=10),
    ))
    assert pos.state is LegState.FLAT
    assert pos.hedge_attempts == 0
    # The only outbound submit was the scratch, not a hedge.
    assert gw.submit_calls[0].side == "SELL"
