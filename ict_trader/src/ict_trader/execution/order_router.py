"""Turn an EntryIntent into a Tradovate-style bracket order spec.

The bracket is an OSO (entry) that, on fill, arms an OCO of a protective stop and scaled
take-profits, plus a *runner* leg whose stop is managed dynamically toward the ERL (it has
no fixed take-profit). The builder is pure so it is unit-tested without a broker.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..domain.enums import OrderType, Side
from ..domain.signals import EntryIntent


def idempotency_key(intent: EntryIntent, leg: str) -> str:
    """Stable key so reconnect/retry never double-submits a leg."""
    raw = f"{intent.ts.isoformat()}|{intent.side.value}|{leg}|{intent.entry_px}|{intent.stop_px}"
    return hashlib.sha1(raw.encode()).hexdigest()[:24]


def _round_to_tick(px: float, tick: float) -> float:
    return round(round(px / tick) * tick, 10)


@dataclass
class BracketLeg:
    leg: str  # entry | stop | tp1 | tp2 | runner
    action: str  # Buy | Sell
    order_type: OrderType
    qty: int
    price: float | None
    stop_price: float | None
    idempotency_key: str


@dataclass
class BracketSpec:
    symbol: str
    side: Side
    total_qty: int
    legs: list[BracketLeg] = field(default_factory=list)


def split_quantity(total: int, fractions: tuple[float, float]) -> tuple[int, int, int]:
    """Split total contracts into (tp1, tp2, runner), guaranteeing >=1 runner if total>=1."""
    if total <= 0:
        return (0, 0, 0)
    if total == 1:
        return (0, 0, 1)  # all runner
    if total == 2:
        return (1, 0, 1)
    f1, f2 = fractions
    q1 = max(1, round(total * f1))
    q2 = max(1, round(total * f2))
    while q1 + q2 >= total:  # keep at least one runner
        if q2 > 1:
            q2 -= 1
        elif q1 > 1:
            q1 -= 1
        else:
            break
    runner = total - q1 - q2
    return (q1, q2, runner)


def build_bracket(
    intent: EntryIntent,
    qty: int,
    *,
    symbol: str,
    tick_size: float = 0.25,
    tp_fractions: tuple[float, float] = (0.4, 0.3),
) -> BracketSpec:
    """Entry OSO + one OCO tranche per scale-out.

    Each tranche carries its own protective stop so the leg quantities never overlap:
    sum of the ``*_stop`` legs equals the entry quantity, and the ``*_tp`` legs cover the
    two scale-outs. The runner tranche has a trailing stop and no fixed take-profit (it is
    trailed toward the ERL by the position manager).
    """
    side = intent.side
    action = "Buy" if side is Side.LONG else "Sell"
    exit_action = "Sell" if side is Side.LONG else "Buy"
    q1, q2, runner = split_quantity(qty, tp_fractions)
    stop_px = _round_to_tick(intent.stop_px, tick_size)

    spec = BracketSpec(symbol=symbol, side=side, total_qty=qty)
    spec.legs.append(BracketLeg(
        "entry", action, OrderType.LIMIT, qty,
        _round_to_tick(intent.entry_px, tick_size), None, idempotency_key(intent, "entry")))

    tranches = [
        ("tp1", q1, _round_to_tick(intent.tp1_px, tick_size), OrderType.STOP),
        ("tp2", q2, _round_to_tick(intent.tp2_px, tick_size), OrderType.STOP),
        ("runner", runner, None, OrderType.TRAILING_STOP),
    ]
    for name, q, tp_px, stop_type in tranches:
        if q <= 0:
            continue
        spec.legs.append(BracketLeg(
            f"{name}_stop", exit_action, stop_type, q, None, stop_px,
            idempotency_key(intent, f"{name}_stop")))
        if tp_px is not None:
            spec.legs.append(BracketLeg(
                f"{name}_tp", exit_action, OrderType.LIMIT, q, tp_px, None,
                idempotency_key(intent, f"{name}_tp")))
    return spec
