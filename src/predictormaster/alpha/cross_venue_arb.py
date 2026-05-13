"""Cross-venue arbitrage scanner (alpha α2).

The signal: same real-world event prices differently on Polymarket,
Kalshi, and the sportsbook consensus. When the YES-share equivalent
costs sum to less than 1 minus round-trip cost, buying both sides
locks in a riskless return.

Scope of this v1
----------------
Detection is venue-agnostic. **Execution** is Polymarket-only — the
companion ``to_polymarket_legs`` helper emits ``OrderRequest`` objects
for the PM leg(s) only. The non-PM legs are surfaced as
``ManualLeg`` records the operator can hedge by hand (Kalshi UI,
sportsbook account) or skip when the PM-only EV is sufficient on its
own.

Cost model (per leg, in YES-share units 0..1)
---------------------------------------------
Polymarket: 2 % taker fee + 0.5 % slippage budget (conservative;
the real slippage comes from the OB walk and is added on top).
Kalshi: 0.5 % maker/taker fee (Kalshi's tiered fee schedule rounds
down to roughly that for sub-$10 fills).
Sportsbooks: 0 explicit fee — the vig is already in the implied
probability we de-vigged out at ingestion.

Safety margin
-------------
We refuse to count an arb as real until edge ≥ ``min_edge``
(default 1.5 % of total stake) after all per-leg costs. Polymarket
order books move; a thin edge evaporates before the second leg
fills.

This module makes NO HTTP calls. It consumes the registry the
caller has already populated, and the slippage walk is done
elsewhere when the executor converts ``ArbOpportunity`` into orders.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from ..execution.polymarket_clob import OrderRequest
from ..live.registry import LiveGame, MarketRef

# Per-venue round-trip cost in YES-share units (decimal, NOT %).
VENUE_COST = {
    "polymarket": 0.025,   # 2 % taker + 0.5 % slippage budget
    "kalshi":     0.005,
    "sportsbooks": 0.0,    # vig already removed at ingestion
}


@dataclass(frozen=True)
class ArbLeg:
    """One side of a 2-leg arbitrage."""
    venue: str
    market_id: str
    side: str            # "home" | "away"
    price: float         # YES-share-equivalent (0..1)
    cost: float          # venue-specific round-trip cost (0..1)


@dataclass(frozen=True)
class ArbOpportunity:
    """A pair of legs that, when both filled, locks in ``edge``.

    ``edge`` is per unit stake: a $10 total stake at edge=0.02 returns
    $0.20 over and above the $10 risked, regardless of who wins.
    """
    game_id: str
    league: str
    home: str
    away: str
    leg_home: ArbLeg     # the leg you'd buy on the home outcome
    leg_away: ArbLeg     # the leg you'd buy on the away outcome
    total_cost: float    # leg_home.price + leg_home.cost + leg_away.price + leg_away.cost
    edge: float          # 1 - total_cost  (positive ⇒ arb)


@dataclass(frozen=True)
class ManualLeg:
    """Leg the caller must execute by hand (non-Polymarket venues)."""
    venue: str
    market_id: str
    side: str
    target_price: float
    notional_usd: float


def _leg_for_venue(venue: str, ref: MarketRef, side: str) -> ArbLeg:
    price = ref.implied_home if side == "home" else ref.implied_away
    return ArbLeg(
        venue=venue,
        market_id=ref.market_id,
        side=side,
        price=float(price),
        cost=VENUE_COST.get(venue, 0.0),
    )


def _arb_for_pair(
    game: LiveGame,
    venue_a: str,
    venue_b: str,
) -> ArbOpportunity | None:
    """Best of the two side-assignments for two given venues.

    Buy "home" on venue_a + "away" on venue_b, OR the reverse.
    Returns the configuration with the larger edge if positive, else None.
    """
    ref_a = game.venues[venue_a]
    ref_b = game.venues[venue_b]
    candidates: list[ArbOpportunity] = []
    for side_a, _side_b in (("home", "away"), ("away", "home")):
        leg_h = _leg_for_venue(venue_a if side_a == "home" else venue_b,
                               ref_a if side_a == "home" else ref_b,
                               "home")
        leg_a = _leg_for_venue(venue_a if side_a == "away" else venue_b,
                               ref_a if side_a == "away" else ref_b,
                               "away")
        # Skip if any price is zero/invalid — registry gave us no real quote
        if leg_h.price <= 0 or leg_a.price <= 0:
            continue
        if leg_h.price >= 1 or leg_a.price >= 1:
            continue
        total = leg_h.price + leg_h.cost + leg_a.price + leg_a.cost
        edge = 1.0 - total
        candidates.append(ArbOpportunity(
            game_id=game.game_id, league=game.league,
            home=game.home, away=game.away,
            leg_home=leg_h, leg_away=leg_a,
            total_cost=total, edge=edge,
        ))
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.edge)
    return best


def scan(
    games: Iterable[LiveGame],
    *,
    min_edge: float = 0.015,
    venues: tuple[str, ...] = ("polymarket", "kalshi", "sportsbooks"),
) -> list[ArbOpportunity]:
    """Return arbitrage opportunities across the supplied games.

    Only games with ≥2 of ``venues`` present are considered. The best
    edge per game (across all venue-pairs) is returned; ties broken by
    venue-pair lexicographic order. Use ``min_edge`` to filter — the
    default 1.5 % is a conservative margin above per-leg costs.
    """
    out: list[ArbOpportunity] = []
    for g in games:
        present = [v for v in venues if v in g.venues]
        if len(present) < 2:
            continue
        best: ArbOpportunity | None = None
        for va, vb in combinations(present, 2):
            cand = _arb_for_pair(g, va, vb)
            if cand is None:
                continue
            if best is None or cand.edge > best.edge:
                best = cand
        if best is not None and best.edge >= min_edge:
            out.append(best)
    out.sort(key=lambda o: -o.edge)
    return out


def equal_profit_sizes(opp: ArbOpportunity, total_stake_usd: float) -> tuple[float, float]:
    """Allocate ``total_stake_usd`` across the two legs so that PnL is
    identical regardless of outcome.

    Solve:  s_h / p_h  =  s_a / p_a   (equal payout)
            s_h + s_a   = total_stake_usd
    ⇒ s_h = total · p_h / (p_h + p_a)
    """
    p_h = opp.leg_home.price
    p_a = opp.leg_away.price
    denom = p_h + p_a
    if denom <= 0:
        return (0.0, 0.0)
    s_h = total_stake_usd * p_h / denom
    s_a = total_stake_usd - s_h
    return (s_h, s_a)


def to_polymarket_legs(
    opp: ArbOpportunity,
    total_stake_usd: float,
    *,
    token_id_lookup: dict[tuple[str, str], str] | None = None,
) -> tuple[list[OrderRequest], list[ManualLeg]]:
    """Split an opportunity into Polymarket OrderRequests + manual legs.

    ``token_id_lookup`` maps (market_id, side) → CLOB token_id; needed
    because Polymarket order placement is per outcome-token, not per
    market. If a Polymarket leg has no token_id, it falls through to a
    ManualLeg so the operator can still execute it via the PM UI.
    """
    s_h, s_a = equal_profit_sizes(opp, total_stake_usd)
    poly_reqs: list[OrderRequest] = []
    manual: list[ManualLeg] = []

    for leg, notional in ((opp.leg_home, s_h), (opp.leg_away, s_a)):
        if notional <= 0:
            continue
        if leg.venue == "polymarket":
            token = (token_id_lookup or {}).get((leg.market_id, leg.side))
            if token is None:
                manual.append(ManualLeg(
                    venue=leg.venue, market_id=leg.market_id,
                    side=leg.side, target_price=leg.price,
                    notional_usd=notional,
                ))
                continue
            # PM is bought in YES-share units. Shares = USDC notional / price.
            size = notional / leg.price if leg.price > 0 else 0.0
            poly_reqs.append(OrderRequest(
                token_id=token,
                side="BUY",
                price=leg.price,
                size=size,
                order_type="GTC",
            ))
        else:
            manual.append(ManualLeg(
                venue=leg.venue, market_id=leg.market_id,
                side=leg.side, target_price=leg.price,
                notional_usd=notional,
            ))
    return poly_reqs, manual
