"""Tests for ops.diagnose — verdict logic, journal summary, suggestions.

The live edge-sample function is not exercised here (it touches
Polymarket's API); instead we build an ``EdgeSample`` directly and
verify the verdict logic correctly classifies it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from predictormaster.ops.diagnose import (
    EdgeSample,
    Verdict,
    diagnose,
    summarise_journal,
)
from predictormaster.ops.metrics import load_decisions


def _write_journal(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _sample(*, best: float, n_with_books: int = 80, n_above_zero: int = 0,
            n_above_0pt1: int = 0, n_above_0pt5: int = 0,
            top: list[dict] | None = None) -> EdgeSample:
    return EdgeSample(
        n_pairs_attempted=n_with_books,
        n_pairs_with_books=n_with_books,
        best_edge=best,
        median_edge=best - 0.02,
        edges_above_zero=n_above_zero,
        edges_above_0pt1pct=n_above_0pt1,
        edges_above_0pt3pct=0,
        edges_above_0pt5pct=n_above_0pt5,
        edges_above_1pct=0,
        top_5_edges=top or [],
        sampled_utc=datetime.now(timezone.utc).isoformat(),
        sample_elapsed_s=10.0,
    )


# ---------------- journal summary ----------------

def test_summarise_empty_journal() -> None:
    s = summarise_journal([])
    assert s.n_total == 0
    assert s.n_accepted == 0
    assert s.last_decision_age_seconds is None


def test_summarise_counts_rejections_by_reason(tmp_path: Path) -> None:
    rows = [
        {"alpha": "α2", "mode": "shadow", "accepted": False,
         "rejection_reason": "edge below min_edge",
         "requested_size": 1, "requested_price": 0.5, "timestamp": f"t{i}"}
        for i in range(5)
    ] + [
        {"alpha": "α2", "mode": "shadow", "accepted": False,
         "rejection_reason": "max_daily_notional reached",
         "requested_size": 1, "requested_price": 0.5, "timestamp": f"t{i+10}"}
        for i in range(2)
    ]
    j = tmp_path / "j.jsonl"
    _write_journal(j, rows)
    s = summarise_journal(load_decisions(j))
    assert s.n_rejected == 7
    assert s.n_by_reason["edge below min_edge"] == 5
    assert s.n_by_reason["max_daily_notional reached"] == 2


def test_summarise_computes_last_decision_age(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    past = (now - timedelta(seconds=30)).isoformat()
    rows = [{"alpha": "α2", "mode": "shadow", "accepted": False,
             "requested_size": 1, "requested_price": 0.5, "timestamp": past}]
    j = tmp_path / "j.jsonl"
    _write_journal(j, rows)
    s = summarise_journal(load_decisions(j))
    assert s.last_decision_age_seconds is not None
    assert 20 < s.last_decision_age_seconds < 60


# ---------------- verdict logic ----------------

def test_verdict_no_opportunity_when_all_edges_negative(tmp_path: Path) -> None:
    j = tmp_path / "j.jsonl"
    _write_journal(j, [])
    sample = _sample(best=-0.021, n_above_zero=0)
    r = diagnose(journal_path=j, edge_sample=sample)
    assert r.verdict == Verdict.NO_OPPORTUNITY.value
    # at least one actionable suggestion (switch alpha / start logger)
    assert len(r.suggestions) >= 1
    # NO_OPPORTUNITY must NOT suggest lowering min_edge — pointless when
    # best is negative
    for s in r.suggestions:
        assert s.params.get("min_edge") is None


def test_verdict_params_too_tight_when_near_misses(tmp_path: Path) -> None:
    j = tmp_path / "j.jsonl"
    _write_journal(j, [])
    sample = _sample(best=0.003, n_above_zero=5, n_above_0pt1=5, n_above_0pt5=0)
    r = diagnose(journal_path=j, edge_sample=sample)
    assert r.verdict == Verdict.PARAMS_TOO_TIGHT.value
    # Should suggest a specific lowered min_edge
    sug = next((s for s in r.suggestions if "min_edge" in s.params), None)
    assert sug is not None
    assert 0 < sug.params["min_edge"] < 0.005


def test_verdict_risk_gate_blocking_when_dominant_reject_is_risk(tmp_path: Path) -> None:
    rows = [{"alpha": "α2", "mode": "paper", "accepted": False,
             "rejection_reason": "stake capped by max_daily_notional",
             "requested_size": 1, "requested_price": 0.5,
             "timestamp": f"t{i}"} for i in range(10)]
    j = tmp_path / "j.jsonl"
    _write_journal(j, rows)
    # No sample — fall through to journal-based diagnosis
    r = diagnose(journal_path=j, edge_sample=None)
    assert r.verdict == Verdict.RISK_GATE_BLOCKING.value


def test_verdict_healthy_when_many_fills(tmp_path: Path) -> None:
    rows = [{"alpha": "α2", "mode": "paper", "accepted": True,
             "requested_size": 1, "requested_price": 0.5, "pnl_usd": 0.02,
             "timestamp": f"t{i}"} for i in range(10)]
    j = tmp_path / "j.jsonl"
    _write_journal(j, rows)
    r = diagnose(journal_path=j, edge_sample=None)
    assert r.verdict == Verdict.HEALTHY.value
    assert r.suggestions == []


def test_verdict_unknown_when_no_data(tmp_path: Path) -> None:
    j = tmp_path / "j.jsonl"
    _write_journal(j, [])
    r = diagnose(journal_path=j, edge_sample=None)
    assert r.verdict == Verdict.UNKNOWN.value


# ---------------- serialisation contract ----------------

def test_report_serialises_to_json(tmp_path: Path) -> None:
    j = tmp_path / "j.jsonl"
    _write_journal(j, [])
    sample = _sample(best=-0.021)
    r = diagnose(journal_path=j, edge_sample=sample)
    blob = r.to_dict()
    # round-trips through JSON
    s = json.dumps(blob)
    again = json.loads(s)
    assert again["verdict"] == r.verdict
    assert again["edge_sample"]["best_edge"] == pytest.approx(-0.021)
