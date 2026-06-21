from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ict_trader.analytics.trade_analyzer import analyze_trade
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Killzone, Side, Symbol, Timeframe


def _bars(closes: list[float], start: datetime) -> list[Bar]:
    out: list[Bar] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append(Bar(
            symbol=Symbol.NQ, timeframe=Timeframe.M5,
            ts_open=start + timedelta(minutes=5 * i),
            open=o, high=max(o, c) + 0.5, low=min(o, c) - 0.5, close=c, volume=100,
        ))
    return out


def test_weights_sum_to_one_and_score_in_range():
    entry = datetime(2024, 5, 15, 14, 0, tzinfo=UTC)
    bars = _bars([100 + i * 0.5 for i in range(30)], entry - timedelta(hours=3))
    a = analyze_trade(side=Side.LONG, entry_ts=entry, bars=bars,
                      killzone=Killzone.NY_AM, path_clean=True)
    assert len(a.elements) == 6
    assert abs(sum(e.weight for e in a.elements) - 1.0) < 1e-9
    assert 0.0 <= a.score <= 1.0
    assert a.grade in {"A", "B", "C", "D"}


def test_timing_and_path_tags_score_directly():
    entry = datetime(2024, 5, 15, 14, 0, tzinfo=UTC)
    bars = _bars([100 + i * 0.5 for i in range(30)], entry - timedelta(hours=3))
    good = analyze_trade(side=Side.LONG, entry_ts=entry, bars=bars,
                         killzone=Killzone.NY_AM, path_clean=True)
    names = {e.name: e.present for e in good.elements}
    assert names["Killzone timing"] is True
    assert names["Clean path (LRLR)"] is True
    # a lunch-killzone, congested-path trade loses those two contributions
    bad = analyze_trade(side=Side.LONG, entry_ts=entry, bars=bars,
                        killzone=Killzone.LUNCH, path_clean=False)
    assert bad.score == round(good.score - 0.25, 3)


def test_breakeven_early_is_flagged_in_summary():
    entry = datetime(2024, 5, 15, 14, 0, tzinfo=UTC)
    bars = _bars([100 + i * 0.5 for i in range(30)], entry - timedelta(hours=3))
    a = analyze_trade(side=Side.LONG, entry_ts=entry, bars=bars,
                      killzone=Killzone.NY_AM, moved_to_be_early=True)
    assert "breakeven early" in a.summary


def test_insufficient_bars_marks_detectors_absent():
    entry = datetime(2024, 5, 15, 14, 0, tzinfo=UTC)
    a = analyze_trade(side=Side.LONG, entry_ts=entry, bars=[],
                      killzone=Killzone.NY_AM, path_clean=True)
    detector_els = [e for e in a.elements if "insufficient bars" in e.detail]
    assert len(detector_els) == 4 and all(not e.present for e in detector_els)
    # only killzone (0.15) + clean path (0.10) contribute
    assert a.score == 0.25
