"""Tests for the cross-venue + intra-Polymarket arb scanners."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from predictormaster.alpha.cross_venue_arb import (
    ArbOpportunity,
    equal_profit_sizes,
    to_polymarket_legs,
)
from predictormaster.alpha.cross_venue_arb import (
    scan as scan_cross,
)
from predictormaster.alpha.intra_poly_arb import (
    OutcomePair,
    detect_one,
    to_orders,
)
from predictormaster.alpha.intra_poly_arb import (
    scan as scan_poly,
)
from predictormaster.execution.polymarket_clob import (
    BookLevel,
    OrderBook,
    PolymarketCLOB,
)
from predictormaster.live.registry import LiveGame, MarketRef


def _game(home_a, away_a, home_b, away_b, *, venues=("polymarket", "kalshi")) -> LiveGame:
    g = LiveGame(
        game_id="nba:1:lakers-celtics",
        league="nba",
        home="Lakers", away="Celtics",
        home_entity_id="lakers", away_entity_id="celtics",
        start_utc=None,
    )
    g.venues[venues[0]] = MarketRef(venues[0], "mkt-a", home_a, away_a)
    g.venues[venues[1]] = MarketRef(venues[1], "mkt-b", home_b, away_b)
    return g


# ---------------- cross_venue_arb ----------------

def test_cross_no_arb_when_prices_match():
    # Both venues price home=0.55, away=0.45. Sum is exactly 1, no edge after fees.
    g = _game(0.55, 0.45, 0.55, 0.45)
    opps = scan_cross([g], min_edge=0.0)
    # cost ≥ 0.025 + 0.005 means total ≥ 1.03 — negative edge
    assert opps == []


def test_cross_finds_real_arb():
    # PM has home cheap (0.48), Kalshi has away cheap (0.48).
    # Cost on PM-home = 0.48 + 0.025; Kalshi-away = 0.48 + 0.005 → total 0.99 → edge 0.01
    g = _game(0.48, 0.55, 0.55, 0.48)
    opps = scan_cross([g], min_edge=0.005)
    assert len(opps) == 1
    o = opps[0]
    # Best config: PM home + Kalshi away
    assert o.leg_home.venue == "polymarket"
    assert o.leg_away.venue == "kalshi"
    assert o.edge > 0.005
    assert o.edge < 0.02


def test_cross_filters_below_min_edge():
    g = _game(0.49, 0.55, 0.55, 0.49)   # tiny edge
    assert scan_cross([g], min_edge=0.05) == []   # demanding 5% — none qualify


def test_cross_requires_two_venues():
    g = LiveGame(
        game_id="x", league="nba", home="A", away="B",
        home_entity_id="a", away_entity_id="b", start_utc=None,
    )
    g.venues["polymarket"] = MarketRef("polymarket", "m", 0.4, 0.6)
    assert scan_cross([g]) == []


def test_cross_skips_invalid_prices():
    g = _game(0.0, 0.5, 0.5, 0.0)   # both legs zero → invalid
    assert scan_cross([g]) == []


def test_equal_profit_sizes_balances_payout():
    opp = ArbOpportunity(
        game_id="g", league="nba", home="A", away="B",
        leg_home=type("L", (), dict(venue="polymarket", market_id="m",
                                    side="home", price=0.4, cost=0.025))(),
        leg_away=type("L", (), dict(venue="kalshi", market_id="m2",
                                    side="away", price=0.55, cost=0.005))(),
        total_cost=0.98, edge=0.02,
    )
    s_h, s_a = equal_profit_sizes(opp, total_stake_usd=10.0)
    assert pytest.approx(s_h + s_a) == 10.0
    # Equal-payout property: shares are s/p; must match across legs
    assert pytest.approx(s_h / 0.4, rel=1e-6) == pytest.approx(s_a / 0.55, rel=1e-6)


def test_to_polymarket_legs_emits_pm_order_and_manual_other():
    g = _game(0.48, 0.55, 0.55, 0.48)
    opps = scan_cross([g], min_edge=0.005)
    opp = opps[0]
    # Provide a token for the PM home leg
    token_map = {("mkt-a", "home"): "TOKEN-HOME"}
    poly, manual = to_polymarket_legs(opp, total_stake_usd=10.0, token_id_lookup=token_map)
    assert len(poly) == 1
    assert poly[0].token_id == "TOKEN-HOME"
    assert poly[0].side == "BUY"
    assert poly[0].size > 0
    assert len(manual) == 1
    assert manual[0].venue == "kalshi"


def test_to_polymarket_legs_no_token_falls_to_manual():
    g = _game(0.48, 0.55, 0.55, 0.48)
    opp = scan_cross([g], min_edge=0.005)[0]
    poly, manual = to_polymarket_legs(opp, total_stake_usd=10.0, token_id_lookup={})
    assert poly == []
    assert len(manual) == 2


# ---------------- intra_poly_arb ----------------

def _book(asks):
    return OrderBook(
        token_id="t",
        bids=(),
        asks=tuple(BookLevel(p, s) for p, s in asks),
        fetched_utc=datetime.now(timezone.utc),
    )


def test_intra_no_arb_at_par():
    pair = OutcomePair("cid", "Lakers win?", "yt", "nt")
    # YES=0.55 + NO=0.45 = 1.00, plus 2% fees → no arb
    a = detect_one(pair, _book([(0.55, 100)]), _book([(0.45, 100)]))
    assert a is None


def test_intra_detects_arb():
    pair = OutcomePair("cid", "Lakers win?", "yt", "nt")
    # YES=0.45 + NO=0.45 = 0.90, fee ≈ 0.018, edge ≈ 0.082
    a = detect_one(pair, _book([(0.45, 50)]), _book([(0.45, 30)]))
    assert a is not None
    assert a.yes_ask == 0.45
    assert a.no_ask == 0.45
    assert a.max_units == 30          # bounded by NO depth
    assert a.edge > 0.07


def test_intra_below_min_edge_returns_none():
    pair = OutcomePair("cid", "q", "yt", "nt")
    # YES=0.49 + NO=0.50 = 0.99, fees push it negative
    assert detect_one(pair, _book([(0.49, 10)]), _book([(0.50, 10)])) is None


def test_intra_empty_book_returns_none():
    pair = OutcomePair("cid", "q", "yt", "nt")
    assert detect_one(pair, _book([]), _book([(0.45, 10)])) is None


def test_intra_to_orders_equal_payout_and_capped():
    pair = OutcomePair("cid", "q", "yt", "nt")
    a = detect_one(pair, _book([(0.45, 1000)]), _book([(0.45, 1000)]))
    yes_o, no_o = to_orders(a, total_stake_usd=10.0)
    assert yes_o.side == "BUY" and no_o.side == "BUY"
    assert yes_o.order_type == "IOC"
    # Equal-payout: same share count on each side at equal prices
    assert pytest.approx(yes_o.size, rel=1e-6) == no_o.size
    # Caps at max_units (which is 1000 here, far above what $10 would buy)
    assert yes_o.size <= a.max_units


def test_intra_scan_with_fake_clob():
    pair = OutcomePair("cid", "q", "yt", "nt")
    # Inject a fake HTTP that returns different books depending on token_id
    def fake_http(url, params):
        tid = params.get("token_id") if params else None
        if tid == "yt":
            return {"market": "yt", "bids": [], "asks": [{"price": "0.45", "size": "50"}]}
        if tid == "nt":
            return {"market": "nt", "bids": [], "asks": [{"price": "0.45", "size": "50"}]}
        return {}
    clob = PolymarketCLOB(http=fake_http)
    arbs = scan_poly(clob, [pair])
    assert len(arbs) == 1
    assert arbs[0].condition_id == "cid"
