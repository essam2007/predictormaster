"""Fill-rate diagnostics + actionable suggestions for the ops dashboard.

Three signals are combined to answer the question
"why aren't orders filling?":

1. **Live edge sample** — fresh scan of Polymarket's top markets, returns
   the actual edge distribution (best, median, n_above_threshold). Tells
   us whether the strategy parameters are tight or whether the market
   itself has no arb today.

2. **Journal analysis** — recent decisions in ``logs/decisions.jsonl``.
   Counts by mode, rejection reason, near-miss density.

3. **Verdict** — combines (1) and (2) into one of four states:
     - NO_OPPORTUNITY: market structure has no arbs at any reasonable
       threshold; loosening params will not help
     - PARAMS_TOO_TIGHT: real near-misses present; recommend lowering
       min_edge to a specific value computed from the sample
     - RISK_GATE_BLOCKING: arbs detected but rejected by risk gates
     - HEALTHY: orders filling — no action needed

Suggestions are NEVER auto-applied. The dashboard surfaces them as
prefilled values in the Start modal; the operator confirms.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .metrics import DecisionRow, load_decisions

logger = logging.getLogger(__name__)

DEFAULT_JOURNAL = Path("logs/decisions.jsonl")


class Verdict(str, Enum):
    NO_OPPORTUNITY = "no_opportunity"
    PARAMS_TOO_TIGHT = "params_too_tight"
    RISK_GATE_BLOCKING = "risk_gate_blocking"
    HEALTHY = "healthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EdgeSample:
    """Snapshot of edge distribution from one fresh scan."""
    n_pairs_attempted: int
    n_pairs_with_books: int
    best_edge: float | None
    median_edge: float | None
    edges_above_zero: int
    edges_above_0pt1pct: int
    edges_above_0pt3pct: int
    edges_above_0pt5pct: int
    edges_above_1pct: int
    top_5_edges: list[dict[str, Any]]   # [{edge, ya, na, question}]
    sampled_utc: str
    sample_elapsed_s: float

    def to_dict(self) -> dict:
        return {**self.__dict__}


@dataclass(frozen=True)
class JournalSummary:
    n_total: int
    n_by_mode: dict[str, int]
    n_by_reason: dict[str, int]
    n_accepted: int
    n_rejected: int
    last_decision_age_seconds: float | None

    def to_dict(self) -> dict:
        return {**self.__dict__}


@dataclass(frozen=True)
class Suggestion:
    title: str                 # human-readable, one sentence
    detail: str                # why we suggest it
    params: dict[str, Any]     # prefill values for the Start modal — keys match StartRequest

    def to_dict(self) -> dict:
        return {**self.__dict__}


@dataclass(frozen=True)
class DiagnosticReport:
    generated_utc: str
    verdict: str
    verdict_summary: str
    edge_sample: EdgeSample | None
    journal: JournalSummary
    suggestions: list[Suggestion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_utc": self.generated_utc,
            "verdict": self.verdict,
            "verdict_summary": self.verdict_summary,
            "edge_sample": self.edge_sample.to_dict() if self.edge_sample else None,
            "journal": self.journal.to_dict(),
            "suggestions": [s.to_dict() for s in self.suggestions],
            "notes": list(self.notes),
        }


# ---------------- journal summary ----------------

def summarise_journal(rows: list[DecisionRow]) -> JournalSummary:
    if not rows:
        return JournalSummary(
            n_total=0, n_by_mode={}, n_by_reason={},
            n_accepted=0, n_rejected=0, last_decision_age_seconds=None,
        )
    n_total = len(rows)
    n_accepted = sum(1 for r in rows if r.accepted)
    n_rejected = n_total - n_accepted
    by_mode = dict(Counter(r.mode for r in rows))
    by_reason = dict(Counter(r.rejection_reason for r in rows if r.rejection_reason))
    # last decision age — best-effort
    last_age: float | None = None
    last_ts = rows[-1].timestamp
    try:
        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        last_age = (datetime.now(timezone.utc) - dt).total_seconds()
    except (ValueError, AttributeError):
        pass
    return JournalSummary(
        n_total=n_total,
        n_by_mode=by_mode,
        n_by_reason=by_reason,
        n_accepted=n_accepted,
        n_rejected=n_rejected,
        last_decision_age_seconds=last_age,
    )


# ---------------- live edge sample ----------------

def sample_polymarket_edges(
    *,
    limit: int = 80,
    fee_per_leg: float = 0.02,
    timeout_seconds: float = 90.0,
) -> EdgeSample | None:
    """One pass over the top-``limit`` Polymarket binary markets,
    computing 1 − YES_ask − NO_ask − 2·fee for each. Returns ``None`` if
    discovery itself fails (network down, Gamma unavailable).

    This is the same math the live runner uses internally. Running it
    here gives the dashboard a fresh, independent measurement of whether
    arbs exist *right now* without waiting for the runner to log them.
    """
    t0 = time.perf_counter()
    try:
        # Local imports — these modules touch the network and pull in
        # py-clob-client lazily.
        # Reuse the runner's HTTP transport so set_http is wired the
        # same way as in production. We import lazily to avoid forcing
        # scripts/ onto sys.path at module-load time.
        import sys

        from ..data.ingestion import sources as ingest_sources
        scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
        if str(scripts_dir.parent) not in sys.path:
            sys.path.insert(0, str(scripts_dir.parent))
        from scripts.live_runner import _discover_pairs, _real_http

        from ..execution.polymarket_clob import PolymarketCLOB

        ingest_sources.set_http(_real_http)
        clob = PolymarketCLOB(http=_real_http)
        pairs = _discover_pairs(limit=limit)
    except Exception as e:
        logger.warning("edge sample discovery failed: %s", e)
        return None

    edges: list[tuple[float, float, float, str]] = []
    deadline = t0 + timeout_seconds
    for p in pairs:
        if time.perf_counter() > deadline:
            break
        try:
            yb = clob.get_book(p.yes_token_id)
            nb = clob.get_book(p.no_token_id)
        except Exception:
            continue
        if not yb.asks or not nb.asks:
            continue
        ya = yb.asks[0].price
        na = nb.asks[0].price
        fee = (ya + na) * fee_per_leg
        edge = 1.0 - ya - na - fee
        edges.append((edge, ya, na, p.question[:80]))

    edges.sort(reverse=True)
    arr = [e for e, *_ in edges]
    if not arr:
        return EdgeSample(
            n_pairs_attempted=len(pairs), n_pairs_with_books=0,
            best_edge=None, median_edge=None,
            edges_above_zero=0, edges_above_0pt1pct=0, edges_above_0pt3pct=0,
            edges_above_0pt5pct=0, edges_above_1pct=0,
            top_5_edges=[],
            sampled_utc=datetime.now(timezone.utc).isoformat(),
            sample_elapsed_s=time.perf_counter() - t0,
        )
    arr_sorted = sorted(arr)
    median = arr_sorted[len(arr_sorted) // 2]
    return EdgeSample(
        n_pairs_attempted=len(pairs),
        n_pairs_with_books=len(arr),
        best_edge=max(arr),
        median_edge=median,
        edges_above_zero=sum(1 for e in arr if e >= 0.0),
        edges_above_0pt1pct=sum(1 for e in arr if e >= 0.001),
        edges_above_0pt3pct=sum(1 for e in arr if e >= 0.003),
        edges_above_0pt5pct=sum(1 for e in arr if e >= 0.005),
        edges_above_1pct=sum(1 for e in arr if e >= 0.010),
        top_5_edges=[
            {"edge": float(e), "yes_ask": float(ya), "no_ask": float(na),
             "question": q}
            for e, ya, na, q in edges[:5]
        ],
        sampled_utc=datetime.now(timezone.utc).isoformat(),
        sample_elapsed_s=time.perf_counter() - t0,
    )


# ---------------- combined verdict ----------------

def _verdict_and_suggestions(
    sample: EdgeSample | None,
    journal: JournalSummary,
) -> tuple[Verdict, str, list[Suggestion]]:
    notes: list[str] = []
    suggestions: list[Suggestion] = []

    # Easy case first: orders ARE filling
    if journal.n_accepted >= 5:
        return (Verdict.HEALTHY,
                f"{journal.n_accepted} fills logged; system is operating.",
                [])

    # If we have a sample, the live edge distribution is the primary signal
    if sample is not None and sample.n_pairs_with_books >= 20:
        best = sample.best_edge or float("-inf")
        if sample.edges_above_zero == 0:
            verdict_text = (
                f"No arb in current market: best edge {best*100:+.2f}% "
                f"(median {(sample.median_edge or 0)*100:+.2f}%) across "
                f"{sample.n_pairs_with_books} markets. Polymarket MMs keep "
                f"YES+NO ≈ $1.005, inside the 4% round-trip fee envelope. "
                f"Lowering min_edge will NOT help."
            )
            suggestions.append(Suggestion(
                title="Switch to α3-sentiment or α6-public-bias-fade",
                detail=(
                    "α2 intra-poly arb is structurally unfilled at current PM "
                    "spreads. α3 needs sub-minute text feeds; α6 needs "
                    "THE_ODDS_API_KEY. Both will fire under different market "
                    "conditions than intra-poly arb."
                ),
                params={},
            ))
            suggestions.append(Suggestion(
                title="Start the snapshot logger to catch transient dislocations",
                detail=(
                    "PM books are tight on average but occasionally drift wide "
                    "around news events. The snapshot logger records every 5s "
                    "so the post-hoc α2 evaluator can find the windows when "
                    "an arb DID exist. No fills today, but data accumulates."
                ),
                params={},
            ))
            return Verdict.NO_OPPORTUNITY, verdict_text, suggestions

        if sample.edges_above_0pt5pct == 0 and sample.edges_above_0pt1pct >= 1:
            # Some near-misses; recommend a lower min_edge near the best edge
            target = max(0.0005, float(best) * 0.5)   # half the best, floor 0.05%
            suggestions.append(Suggestion(
                title=f"Lower min_edge to {target*100:.2f}% to capture near-misses",
                detail=(
                    f"{sample.edges_above_0pt1pct} markets have edge ≥ 0.10% but "
                    f"none clear your current 0.50% threshold. Best is "
                    f"{best*100:+.3f}%. Caveat: net of slippage and a 1-tick "
                    f"book move during paired dispatch, these may still go red."
                ),
                params={"min_edge": round(target, 4)},
            ))
            return (
                Verdict.PARAMS_TOO_TIGHT,
                (f"{sample.edges_above_0pt1pct} edges ≥ 0.10%, 0 above 0.50%. "
                 f"Lowering min_edge could capture near-misses but slippage risk rises."),
                suggestions,
            )

    # If journal shows rejections, surface the top reason
    if journal.n_rejected > 0 and journal.n_by_reason:
        top_reason, top_count = max(journal.n_by_reason.items(), key=lambda x: x[1])
        if "edge" in top_reason.lower():
            return (
                Verdict.PARAMS_TOO_TIGHT,
                f"{top_count} rejections for {top_reason!r}.",
                [Suggestion(
                    title="Lower min_edge",
                    detail="Edge gate is the dominant reject reason. Try 0.20% (0.002).",
                    params={"min_edge": 0.002},
                )],
            )
        if any(k in top_reason.lower() for k in ("stake", "risk", "bankroll", "drawdown")):
            return (
                Verdict.RISK_GATE_BLOCKING,
                f"{top_count} rejections for {top_reason!r}.",
                [Suggestion(
                    title="Risk gate is blocking orders",
                    detail=(
                        "Review max_stake / max_daily_notional / drawdown. The "
                        "intent is to NOT auto-loosen these — investigate why "
                        "the strategy keeps hitting the gate first."
                    ),
                    params={},
                )],
            )

    # No journal, no sample (or sample inconclusive) — unknown
    notes.append("Insufficient data for a verdict. Run a few scan cycles first.")
    return Verdict.UNKNOWN, "Insufficient data.", []


def diagnose(
    *,
    journal_path: Path = DEFAULT_JOURNAL,
    edge_sample: EdgeSample | None = None,
) -> DiagnosticReport:
    """Build the full diagnostic report.

    The caller is responsible for choosing whether to take a live edge
    sample (expensive: ~30s of book reads) or skip it. The dashboard
    samples on a slow cadence (every 5 min) and reuses the result across
    fast polls.
    """
    rows = load_decisions(journal_path)
    j_sum = summarise_journal(rows)
    verdict, summary, suggestions = _verdict_and_suggestions(edge_sample, j_sum)
    notes: list[str] = []
    if edge_sample is None:
        notes.append("Edge sample not available (skipped or fetch failed).")
    if not rows:
        notes.append(
            "Decisions journal is empty — runner has either not started, "
            "found zero arbs, or the buffering bug from earlier sessions "
            "may still be active in your build."
        )
    return DiagnosticReport(
        generated_utc=datetime.now(timezone.utc).isoformat(),
        verdict=verdict.value,
        verdict_summary=summary,
        edge_sample=edge_sample,
        journal=j_sum,
        suggestions=suggestions,
        notes=notes,
    )
