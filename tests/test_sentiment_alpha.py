"""Tests for the α3 sentiment pipeline + mask-first backtester."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from predictormaster.alpha.sentiment_alpha import (
    RollingSentimentZ,
    SentimentObservation,
    SentimentPipeline,
    ShockGate,
    ShockSignal,
    calibrate_z_to_dprob,
    causal_backtest,
    window_tradability_mask,
)
from predictormaster.nlp.ner import (
    ContextualNER,
    DictionaryNER,
    EntityMention,
    build_sports_universe,
    confidence_threshold,
    merge_layers,
)
from predictormaster.nlp.sentiment import LexiconScorer

UTC = timezone.utc


# ============================================================
# NER
# ============================================================

def _toy_universe() -> DictionaryNER:
    return DictionaryNER.from_universe(build_sports_universe({
        "epl": [
            ("man_utd", ["Manchester United", "Man Utd", "Man United", "MUFC", "United"]),
            ("man_city", ["Manchester City", "Man City", "MCFC", "City"]),
        ],
    }))


def test_dictionary_ner_finds_unambiguous_team():
    ner = _toy_universe()
    out = ner.extract("MUFC look strong tonight")
    assert len(out) == 1
    assert out[0].entity_id == "team:epl:man_utd"
    assert out[0].confidence == 1.0


def test_dictionary_ner_handles_multiword_aliases():
    ner = _toy_universe()
    out = ner.extract("Manchester City beat Manchester United")
    ids = {m.entity_id for m in out}
    assert ids == {"team:epl:man_city", "team:epl:man_utd"}


def test_dictionary_ner_collision_lowers_confidence():
    """'United' is ambiguous (no collision in our test universe because only
    one team has 'united' alias). Force a collision by adding both."""
    ner = DictionaryNER.from_universe({
        "team:nfl:packers": ["Packers", "Green Bay"],
        "team:misc:packers_club": ["Packers"],   # collision
    })
    out = ner.extract("Packers win Sunday")
    assert len(out) >= 2
    for m in out:
        assert m.confidence == 0.5


def test_dictionary_ner_dedupes_to_longest_span():
    """'Man City' must match as one entity, not 'Man' + 'City'."""
    ner = _toy_universe()
    out = ner.extract("Man City news")
    # Should only have the single 'Man City' match.
    assert len(out) == 1
    assert out[0].entity_id == "team:epl:man_city"
    assert "city" in out[0].surface.lower()


def test_contextual_ner_boosts_near_sports_anchors():
    base = _toy_universe()
    ctx = ContextualNER(base=base, boost=0.5, damp=0.4)
    # No anchor: lone mention, confidence damped.
    out_alone = ctx.extract("Man City offered me a coffee this morning")
    # Anchor present: boosted.
    out_anchor = ctx.extract("Man City vs Man Utd kickoff match")
    assert out_alone and out_alone[0].confidence == pytest.approx(0.4)
    assert out_anchor and all(m.confidence >= 1.0 - 1e-9 for m in out_anchor)


def test_confidence_threshold_filters_correctly():
    mentions = [
        EntityMention("a", (0, 1), "a", 0.9, "x"),
        EntityMention("b", (2, 3), "b", 0.4, "x"),
    ]
    out = confidence_threshold(mentions, min_conf=0.5)
    assert [m.entity_id for m in out] == ["a"]


def test_merge_layers_keeps_highest_confidence_per_entity():
    layer1 = [EntityMention("a", (0, 1), "a", 0.4, "dict")]
    layer2 = [EntityMention("a", (0, 1), "a", 0.9, "transformer")]
    out = merge_layers(layer1, layer2)
    assert len(out) == 1
    assert out[0].confidence == 0.9
    assert out[0].source == "transformer"


# ============================================================
# RollingSentimentZ
# ============================================================

def test_rolling_returns_none_below_min_observations():
    rs = RollingSentimentZ(min_observations=5)
    sig = rs.update(SentimentObservation(
        ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        entity_id="e1", polarity=0.5, intensity=0.5,
        topic="injury", source="rss", confidence=0.9,
    ))
    assert sig is None


def test_rolling_emits_high_z_on_sudden_shift():
    rs = RollingSentimentZ(min_observations=5, window_seconds=3600,
                          half_life_seconds=600)
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # 10 baseline obs near 0
    for i in range(10):
        rs.update(SentimentObservation(
            ts=t0 + timedelta(minutes=i),
            entity_id="e1", polarity=0.01, intensity=0.1,
            topic="generic", source="rss", confidence=1.0,
        ))
    # Sudden strongly-negative shock
    sig = rs.update(SentimentObservation(
        ts=t0 + timedelta(minutes=11),
        entity_id="e1", polarity=-0.9, intensity=0.9,
        topic="injury", source="reddit", confidence=1.0,
    ))
    assert sig is not None
    assert sig.z_score < -2.0
    assert sig.direction == -1
    assert sig.topic == "injury"


def test_rolling_corroboration_counts_distinct_sources():
    rs = RollingSentimentZ(min_observations=3, window_seconds=3600)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i, src in enumerate(["rss", "reddit", "x"]):
        sig = rs.update(SentimentObservation(
            ts=t0 + timedelta(minutes=i),
            entity_id="e1", polarity=0.5, intensity=0.5,
            topic="injury", source=src, confidence=1.0,
        ))
    assert sig is not None
    assert sig.n_corroborating_sources == 3


# ============================================================
# ShockGate
# ============================================================

def _sig(z=3.0, sources=2, topic="injury"):
    return ShockSignal(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        entity_id="e1", z_score=z, polarity_now=0.5,
        rolling_mean=0.0, rolling_sd=0.1,
        n_corroborating_sources=sources,
        topic=topic, direction=1 if z > 0 else -1,
    )


def test_gate_passes_clean_signal():
    g = ShockGate()
    assert g.passes(_sig(), market_p=0.5)
    assert g.last_reject_reason is None


def test_gate_rejects_low_z():
    g = ShockGate(z_threshold=2.0)
    assert not g.passes(_sig(z=1.5), market_p=0.5)
    assert "z" in (g.last_reject_reason or "")


def test_gate_rejects_too_few_sources():
    g = ShockGate(min_corroborating_sources=2)
    assert not g.passes(_sig(sources=1), market_p=0.5)
    assert "sources" in (g.last_reject_reason or "")


def test_gate_rejects_disallowed_topic():
    g = ShockGate(allowed_topics=frozenset({"injury", "lineup"}))
    assert not g.passes(_sig(topic="generic"), market_p=0.5)


def test_gate_rejects_extreme_market_p():
    g = ShockGate(market_p_lo=0.10, market_p_hi=0.90)
    assert not g.passes(_sig(), market_p=0.95)
    assert not g.passes(_sig(), market_p=0.05)


# ============================================================
# SentimentPipeline end-to-end
# ============================================================

def test_pipeline_emits_signal_after_corroborated_shock():
    ner = _toy_universe()
    scorer = LexiconScorer()
    pipe = SentimentPipeline(
        ner=ner, sentiment_scorer=scorer,
        rolling=RollingSentimentZ(min_observations=5, window_seconds=3600,
                                  half_life_seconds=600),
    )
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # Build baseline of generic mentions
    for i in range(6):
        pipe.ingest(t0 + timedelta(minutes=i),
                    "Man Utd are playing tonight in the match",
                    source=f"rss-{i}")
    # Sudden 'injury' message
    out = pipe.ingest(
        t0 + timedelta(minutes=10),
        "Man Utd star out with injury — doubtful for match",
        source="reddit",
    )
    # We expect at least one signal back for man_utd.
    ids = {s.entity_id for s in out}
    assert "team:epl:man_utd" in ids


def test_pipeline_skips_when_no_entity_match():
    ner = _toy_universe()
    scorer = LexiconScorer()
    pipe = SentimentPipeline(ner=ner, sentiment_scorer=scorer)
    out = pipe.ingest(datetime(2026, 1, 1, tzinfo=UTC),
                      "totally unrelated free text", source="rss")
    assert out == []


# ============================================================
# Tradability mask
# ============================================================

def test_window_mask_excludes_far_pregame():
    close = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    open_ = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    mask = window_tradability_mask(
        {"e1": (open_, close)},
        min_lead_minutes=60, max_lead_hours=24,
    )
    # 48 hours before close: NOT tradable.
    assert not mask("e1", close - timedelta(hours=48))
    # 12 hours before close: tradable.
    assert mask("e1", close - timedelta(hours=12))
    # At close: tradable.
    assert mask("e1", close)


def test_window_mask_unknown_entity_false():
    mask = window_tradability_mask({})
    assert not mask("unknown", datetime.now(UTC))


# ============================================================
# Causal backtest
# ============================================================

def test_causal_backtest_respects_mask():
    """Half of the signals fall outside the tradable window — they
    must show up as ``n_blocked_by_mask``, not as trades."""
    close = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    open_ = close - timedelta(days=7)
    mask = window_tradability_mask(
        {"e1": (open_, close)}, max_lead_hours=24,
    )
    # 2 signals INSIDE window (close - 6h, close - 1h)
    # 2 signals OUTSIDE window (close - 48h, close + 1h)
    signals = [
        ShockSignal(ts=close - timedelta(hours=h),
                    entity_id="e1", z_score=2.5, polarity_now=0.5,
                    rolling_mean=0.0, rolling_sd=0.2,
                    n_corroborating_sources=2, topic="injury", direction=1)
        for h in [48, 6, 1, -1]    # -1 = post-close
    ]
    book_rows = []
    # Build a book covering -50h to +5h around close.
    for h in range(-50, 6):
        t = close + timedelta(hours=h)
        book_rows.append({"entity_id": "e1", "ts": t,
                          "mid": 0.5, "ask": 0.51, "bid": 0.49})
    book = pd.DataFrame(book_rows)
    res = causal_backtest(signals, book, tradability=mask,
                          holding_minutes=30, fee_per_leg=0.02,
                          bets_per_year=200)
    assert res.n_signals == 4
    assert res.n_blocked_by_mask == 2
    # The 2 tradable signals → ≤2 trades depending on book lookup.
    assert res.n_trades <= 2


def test_causal_backtest_correctly_signs_returns():
    """Positive z → BUY at ask → profit if exit_mid > ask. Test that
    direction is applied properly."""
    close = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    mask = window_tradability_mask(
        {"e1": (close - timedelta(days=2), close)},
        max_lead_hours=48,
    )
    signal = ShockSignal(ts=close - timedelta(hours=2),
                         entity_id="e1", z_score=3.0, polarity_now=0.7,
                         rolling_mean=0.0, rolling_sd=0.2,
                         n_corroborating_sources=2, topic="injury", direction=1)
    book = pd.DataFrame([
        {"entity_id": "e1", "ts": close - timedelta(hours=2, minutes=1),
         "mid": 0.50, "ask": 0.51, "bid": 0.49},
        {"entity_id": "e1", "ts": close - timedelta(hours=1),
         "mid": 0.60, "ask": 0.61, "bid": 0.59},
    ])
    res = causal_backtest([signal], book, tradability=mask,
                          holding_minutes=30, fee_per_leg=0.02)
    assert res.n_trades == 1
    # Entry at ask=0.51, exit at mid=0.60. Gross = (0.60-0.51)/0.51 ≈ 0.176
    # Net = 0.176 - 0.04 = ~0.136
    assert res.per_bet_returns[0] == pytest.approx((0.60 - 0.51) / 0.51 - 0.04, rel=1e-6)


# ============================================================
# Calibration
# ============================================================

def test_calibrate_z_to_dprob_recovers_linear_relation():
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1, size=100)
    true_slope = 0.03
    true_intercept = 0.005
    moves = true_slope * z + true_intercept + rng.normal(0, 0.001, size=100)
    sigs = [ShockSignal(ts=datetime(2026, 1, 1, tzinfo=UTC),
                        entity_id=f"e{i}", z_score=z[i], polarity_now=0,
                        rolling_mean=0, rolling_sd=0.1,
                        n_corroborating_sources=2, topic="injury", direction=1)
            for i in range(100)]
    slope, intercept = calibrate_z_to_dprob(sigs, moves.tolist())
    assert abs(slope - true_slope) < 0.002
    assert abs(intercept - true_intercept) < 0.002


def test_calibrate_returns_zero_when_too_few_obs():
    sigs = [_sig()] * 5
    moves = [0.01] * 5
    assert calibrate_z_to_dprob(sigs, moves) == (0.0, 0.0)
