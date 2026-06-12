"""Intra-Polymarket order-book arb (alpha α2-poly).

Polymarket markets resolve binary: YES-share + NO-share = $1 at
settlement. If you can BUY a YES-ask + BUY the matched NO-ask for less
than $1.00 (after fees), you lock in a riskless return at resolution.

This happens regularly on thin / new markets where one side's book is
stale. Detection is cheap (one OB read per token); execution is two
limit orders on the same venue, no cross-venue hedging or geo concerns.

The PM CLOB exposes YES and NO as **two separate token IDs** under a
single ``condition_id``. Both order books exist independently; their
relationship YES_price + NO_price ≤ 1 - fees is enforced only by
arbitrageurs (us) — the matching engine itself permits crossing.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..execution.polymarket_clob import OrderBook, OrderRequest, PolymarketCLOB

# 2 % taker on each of two legs ⇒ ~4 % on round-trip. We require the
# sum YES_ask + NO_ask + 4 % to be < 1.00 before flagging.
POLY_TAKER_FEE = 0.02


@dataclass(frozen=True)
class OutcomePair:
    """A binary market's two outcome tokens (YES + NO).

    For three-way markets (draw possible) PM uses ``condition_id`` to
    bundle two tokens — soccer markets have a separate "Draw" market
    which we'd treat as its own binary; this scanner only ever pairs
    exactly two tokens.
    """
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str


@dataclass(frozen=True)
class IntraPolyArb:
    condition_id: str
    question: str
    yes_ask: float
    no_ask: float
    yes_ask_size: float
    no_ask_size: float
    fee_total: float          # combined two-leg fee in dollars-per-unit
    edge: float               # 1 - yes_ask - no_ask - fee_total
    max_units: float          # min(yes_ask_size, no_ask_size) — bounded by tightest book
    yes_token_id: str
    no_token_id: str


def _top_ask(book: OrderBook) -> tuple[float, float] | None:
    if not book.asks:
        return None
    a = book.asks[0]
    if a.price <= 0 or a.size <= 0:
        return None
    return (a.price, a.size)


def detect_one(
    pair: OutcomePair,
    yes_book: OrderBook,
    no_book: OrderBook,
    *,
    fee_per_leg: float = POLY_TAKER_FEE,
    min_edge: float = 0.005,
) -> IntraPolyArb | None:
    """Return an arb if YES_ask + NO_ask + fees < 1, else None.

    ``min_edge`` defaults to 0.5 % which is just above noise — the OB
    can move by one tick (= 0.001 typically) between our two POSTs, so
    anything tighter than 0.5 % is at material execution risk.
    """
    yt = _top_ask(yes_book)
    nt = _top_ask(no_book)
    if yt is None or nt is None:
        return None
    yp, ys = yt
    np_, ns = nt
    fee = (yp + np_) * fee_per_leg     # taker fee scales with notional
    edge = 1.0 - yp - np_ - fee
    if edge < min_edge:
        return None
    return IntraPolyArb(
        condition_id=pair.condition_id,
        question=pair.question,
        yes_ask=yp, no_ask=np_,
        yes_ask_size=ys, no_ask_size=ns,
        fee_total=fee, edge=edge,
        max_units=min(ys, ns),
        yes_token_id=pair.yes_token_id,
        no_token_id=pair.no_token_id,
    )


def scan(
    clob: PolymarketCLOB,
    pairs: Iterable[OutcomePair],
    *,
    fee_per_leg: float = POLY_TAKER_FEE,
    min_edge: float = 0.005,
) -> list[IntraPolyArb]:
    """Fetch the YES + NO order book for each pair and return arbs."""
    out: list[IntraPolyArb] = []
    for p in pairs:
        try:
            yb = clob.get_book(p.yes_token_id)
            nb = clob.get_book(p.no_token_id)
        except Exception:
            continue
        a = detect_one(p, yb, nb, fee_per_leg=fee_per_leg, min_edge=min_edge)
        if a is not None:
            out.append(a)
    out.sort(key=lambda x: -x.edge)
    return out


def to_orders(arb: IntraPolyArb, total_stake_usd: float) -> tuple[OrderRequest, OrderRequest]:
    """Convert an arb into two ``BUY``-IOC orders, sized to spend
    ``total_stake_usd`` total and leave PnL outcome-agnostic.

    Equal-payout sizing: spend ``stake * yes / (yes + no)`` on the YES
    leg. Capped at ``max_units`` so we never request more than the
    visible top-of-book.
    """
    denom = arb.yes_ask + arb.no_ask
    if denom <= 0:
        raise ValueError("invalid arb prices")
    yes_notional = total_stake_usd * arb.yes_ask / denom
    no_notional = total_stake_usd - yes_notional
    yes_size = min(yes_notional / arb.yes_ask, arb.max_units)
    no_size = min(no_notional / arb.no_ask, arb.max_units)
    return (
        OrderRequest(token_id=arb.yes_token_id, side="BUY",
                     price=arb.yes_ask, size=yes_size, order_type="IOC"),
        OrderRequest(token_id=arb.no_token_id, side="BUY",
                     price=arb.no_ask, size=no_size, order_type="IOC"),
    )
