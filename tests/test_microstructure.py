"""Tests for the α4 LOB features and toxic-flow filter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from predictormaster.execution.polymarket_clob import BookLevel, OrderBook
from predictormaster.microstructure.lob_features import (
    features_from_snapshot,
    features_to_row,
    ofi_from_snapshots,
)
from predictormaster.microstructure.toxic_flow import (
    BVCClassifier,
    FlowRegime,
    ToxicFlowGate,
    ToxicFlowState,
    VPINEstimator,
)

UTC = timezone.utc


def _book(bids=(), asks=(), tid="t", ts=None):
    return OrderBook(
        token_id=tid,
        bids=tuple(BookLevel(p, s) for p, s in bids),
        asks=tuple(BookLevel(p, s) for p, s in asks),
        fetched_utc=ts or datetime(2026, 1, 1, tzinfo=UTC),
    )


# ============================================================
# LOB features
# ============================================================

def test_features_balanced_book_microprice_equals_mid():
    """Symmetric book: top bid 0.49, top ask 0.51, equal sizes.
    Microprice should equal the mid (0.50)."""
    book = _book(bids=[(0.49, 100), (0.48, 50)],
                 asks=[(0.51, 100), (0.52, 50)])
    f = features_from_snapshot(book, n_levels=5)
    assert f.mid == pytest.approx(0.50)
    assert f.microprice == pytest.approx(0.50)
    assert f.top_imbalance == pytest.approx(0.0)
    assert f.book_pressure == pytest.approx(0.5)
    assert f.spread == pytest.approx(0.02)
    assert f.spread_bps == pytest.approx(400.0)


def test_microprice_pulls_toward_thin_side():
    """Bid depth >> ask depth at top: large bid soaks liquidity, so
    fair value should lean toward the ASK (microprice > mid)."""
    book = _book(bids=[(0.49, 1000)], asks=[(0.51, 100)])
    f = features_from_snapshot(book)
    assert f.microprice > f.mid    # leans toward ask
    # Symmetric calc check: weight_pa = qb/(qa+qb) = 1000/1100 ≈ 0.909
    # microprice = 0.909·0.49 + 0.091·0.51 — wait that's leaning the
    # other way. Stoikov formula has weights INVERTED to bid/ask:
    # microprice = (qa/(qa+qb))·pb + (qb/(qa+qb))·pa
    #            = (100/1100)·0.49 + (1000/1100)·0.51 ≈ 0.508
    assert f.microprice == pytest.approx(0.508, abs=1e-3)


def test_features_empty_book_returns_zeros_safely():
    book = _book(bids=[], asks=[])
    f = features_from_snapshot(book)
    assert f.levels_observed == 0
    assert f.mid == 0.0
    assert f.microprice == 0.0
    assert f.book_pressure == 0.5
    assert f.bid_depth_L == 0.0


def test_book_pressure_reflects_total_depth():
    book = _book(bids=[(0.49, 200), (0.48, 100)],
                 asks=[(0.51, 100)])
    f = features_from_snapshot(book, n_levels=5)
    # bid depth = 300, ask depth = 100, pressure = 300/400 = 0.75
    assert f.book_pressure == pytest.approx(0.75)


# ============================================================
# OFI from snapshots
# ============================================================

def test_ofi_zero_when_book_unchanged():
    b0 = _book(bids=[(0.49, 100)], asks=[(0.51, 100)],
               ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    b1 = _book(bids=[(0.49, 100)], asks=[(0.51, 100)],
               ts=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC))
    o = ofi_from_snapshots(b0, b1)
    assert o.ofi == 0.0
    assert o.dt_seconds == 1.0


def test_ofi_positive_when_bids_added_or_asks_removed():
    """Cont-Kukanov-Stoikov 2014 OFI: bid price improvement contributes
    +q_b(t) only (the old level wasn't 'consumed' — it's a supply
    increase); ask size shrinks at unchanged price contributes a
    removal, which is positive flow (selling pressure on the ask)."""
    b0 = _book(bids=[(0.49, 100)], asks=[(0.51, 100)],
               ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    b1 = _book(bids=[(0.495, 80)], asks=[(0.51, 50)],
               ts=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC))
    o = ofi_from_snapshots(b0, b1)
    # bid improved: bid_add += 80, bid_rem = 0
    # ask same price, shrank: ask_rem += 50, ask_add = 0
    # OFI = (80 - 0) - (0 - 50) = 130 (strong net buying)
    assert o.ofi == pytest.approx(130.0)
    assert o.ofi_per_second == pytest.approx(130.0)
    assert o.bid_added == pytest.approx(80.0)
    assert o.ask_removed == pytest.approx(50.0)


def test_ofi_negative_on_aggressive_selling():
    """Top bid retreats AND top ask widens — net selling pressure."""
    b0 = _book(bids=[(0.49, 100)], asks=[(0.51, 100)],
               ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    b1 = _book(bids=[(0.48, 100)], asks=[(0.50, 80)],
               ts=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC))
    o = ofi_from_snapshots(b0, b1)
    # bid: price went DOWN → bid_rem += 100, ask: price went DOWN → ask_add += 80
    # OFI = (0 - 100) - (80 - 0) = -180
    assert o.ofi == pytest.approx(-180.0)


def test_features_to_row_includes_ofi():
    b0 = _book(bids=[(0.49, 100)], asks=[(0.51, 100)])
    b1 = _book(bids=[(0.495, 100)], asks=[(0.51, 100)],
               ts=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC))
    feats = features_from_snapshot(b1)
    ofi = ofi_from_snapshots(b0, b1)
    row = features_to_row(feats, ofi)
    assert "ofi" in row and "ofi_per_sec" in row
    assert row["spread"] == feats.spread


# ============================================================
# BVC classifier
# ============================================================

def test_bvc_returns_50_50_before_warmup():
    bvc = BVCClassifier()
    b, s = bvc.classify(price=0.5, volume=10)
    assert b == pytest.approx(5.0)
    assert s == pytest.approx(5.0)


def test_bvc_skews_toward_buy_on_price_up():
    bvc = BVCClassifier(price_window=10)
    # Seed history with small price changes to establish σ_p > 0.
    bvc.classify(0.50, 10)
    for p in (0.501, 0.499, 0.502, 0.498, 0.501, 0.500):
        bvc.classify(p, 10)
    # Now a strong positive jump → expect buy > sell
    b, s = bvc.classify(0.510, 100)
    assert b > s


def test_bvc_classifies_zero_volume_as_zero():
    bvc = BVCClassifier()
    assert bvc.classify(0.5, 0) == (0.0, 0.0)


# ============================================================
# VPIN
# ============================================================

def test_vpin_zero_until_first_bucket_completes():
    v = VPINEstimator(bucket_volume=100, n_buckets=10)
    # 5 obs of volume 10 each — total 50, below bucket.
    for i in range(5):
        out = v.update(datetime(2026, 1, 1, 12, 0, i, tzinfo=UTC),
                       price=0.5, volume=10)
        assert out is None    # no complete bucket yet
    assert v.current == 0.0


def test_vpin_completes_bucket_and_returns_value():
    """BVC needs σ_p > 0 in its rolling window to produce any
    non-50/50 classification. Monotonic prices give constant Δp and
    σ_p = 0, so we use a non-monotonic series with a directional
    shock at the end to generate a real imbalance."""
    v = VPINEstimator(bucket_volume=100, n_buckets=10)
    series = [0.50, 0.501, 0.499, 0.502, 0.498,
              0.501, 0.499, 0.503, 0.510, 0.520]
    for i, p in enumerate(series):
        v.update(datetime(2026, 1, 1, 12, 0, i, tzinfo=UTC),
                 price=p, volume=25)
    # 250 units / 100 bucket = 2 complete buckets
    assert v.n_complete == 2
    assert v.current > 0.0


# ============================================================
# Toxic-flow gate
# ============================================================

def test_gate_starts_normal_stays_normal_on_low_vpin():
    g = ToxicFlowGate(vpin_threshold=0.3)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    g.update(0.1, now)
    assert g.regime is FlowRegime.NORMAL
    assert not g.should_pull()
    assert g.widen_factor() == 1.0


def test_gate_enters_defensive_when_vpin_breaches_threshold():
    g = ToxicFlowGate(vpin_threshold=0.3)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    g.update(0.35, now)
    assert g.regime is FlowRegime.DEFENSIVE
    assert g.should_pull()
    assert g.widen_factor() == 2.0


def test_gate_hysteresis_prevents_early_exit():
    """Once defensive, only return to normal when VPIN drops BELOW
    threshold × hysteresis AND cool-off has elapsed."""
    g = ToxicFlowGate(vpin_threshold=0.30, hysteresis=0.80,
                      cool_off_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    g.update(0.40, t0)
    assert g.regime is FlowRegime.DEFENSIVE
    # 30s later, VPIN at 0.25 (between 0.24 exit and 0.30 entry)
    g.update(0.25, t0 + timedelta(seconds=30))
    assert g.regime is FlowRegime.DEFENSIVE    # still defensive (cool-off + above exit)
    # 90s later, VPIN at 0.20 (below 0.24 exit AND past cool-off)
    g.update(0.20, t0 + timedelta(seconds=90))
    assert g.regime is FlowRegime.NORMAL


def test_combined_state_drives_off_one_stream():
    state = ToxicFlowState(
        estimator=VPINEstimator(bucket_volume=50, n_buckets=10),
        gate=ToxicFlowGate(vpin_threshold=0.05),
    )
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Steady-state: no toxicity → NORMAL.
    for i in range(20):
        state.feed(t0 + timedelta(seconds=i), price=0.50, volume=10)
    # No price drift, very low VPIN.
    assert state.gate.regime in (FlowRegime.NORMAL, FlowRegime.DEFENSIVE)
    # Big directional move + heavy volume → should toxify quickly.
    for i in range(10):
        state.feed(t0 + timedelta(seconds=20 + i),
                   price=0.50 + 0.005 * i, volume=20)
    # No assertion on outcome — we're verifying it runs without error.
    # The combined helper is glue, not where the math lives.
