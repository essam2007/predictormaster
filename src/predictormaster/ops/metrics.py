"""Parse logs/decisions.jsonl into operations metrics.

Output schema is the contract the dashboard frontend depends on.
Schema changes here require updating ``ops/static/app.js`` in lockstep.

Per-bet Sharpe convention (NOT the dashboard's √252):
    sr_ann = mean(r) / sd(r) * √bets_per_year      bets_per_year=200

This matches the convention used everywhere else in the project
([[feedback_per_bet_sharpe]]). Sharpe is reported only when n ≥ 5
realised fills; otherwise null. The frontend renders null as "—".
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_JOURNAL = Path("logs/decisions.jsonl")
BETS_PER_YEAR = 200


@dataclass(frozen=True)
class DecisionRow:
    timestamp: str
    alpha: str
    token_id: str
    side: str
    mode: str                     # shadow | paper | live
    accepted: bool
    rejection_reason: str | None
    requested_size: float
    requested_price: float
    expected_fill_price: float | None
    expected_slippage_bps: float | None
    pct_of_book: float | None
    order_id: str | None
    elapsed_ms: float | None
    pnl_usd: float | None         # populated for paper/live realised fills
    notional_usd: float | None    # requested_size * requested_price


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _row_from_dict(d: dict) -> DecisionRow | None:
    try:
        rs = _safe_float(d.get("requested_size")) or 0.0
        rp = _safe_float(d.get("requested_price")) or 0.0
        return DecisionRow(
            timestamp=str(d.get("timestamp") or d.get("ts") or ""),
            alpha=str(d.get("alpha") or "unknown"),
            token_id=str(d.get("token_id") or ""),
            side=str(d.get("side") or ""),
            mode=str(d.get("mode") or "unknown"),
            accepted=bool(d.get("accepted") or False),
            rejection_reason=d.get("rejection_reason") or None,
            requested_size=rs,
            requested_price=rp,
            expected_fill_price=_safe_float(d.get("expected_fill_price")),
            expected_slippage_bps=_safe_float(d.get("expected_slippage_bps")),
            pct_of_book=_safe_float(d.get("pct_of_book")),
            order_id=d.get("order_id") or None,
            elapsed_ms=_safe_float(d.get("elapsed_ms")),
            pnl_usd=_safe_float(d.get("pnl_usd")),
            notional_usd=rs * rp,
        )
    except (TypeError, ValueError):
        return None


def load_decisions(journal: Path = DEFAULT_JOURNAL) -> list[DecisionRow]:
    """Read every line of the journal. Returns oldest→newest.

    Malformed lines are skipped silently — the journal is append-only
    so partial writes during a crash are recoverable by skipping.
    """
    if not journal.exists():
        return []
    rows: list[DecisionRow] = []
    with journal.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = _row_from_dict(obj)
            if row is not None:
                rows.append(row)
    return rows


def _per_bet_sharpe_ann(returns: list[float]) -> float | None:
    if len(returns) < 5:
        return None
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / max(1, n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return None
    return mean / sd * math.sqrt(BETS_PER_YEAR)


def _max_drawdown(returns: list[float]) -> float:
    """Max drawdown on the cumulative equity curve. Returns a NEGATIVE
    number (or 0). Equity is summed in stake-units of return (additive
    on returns_pct), which matches the per-bet convention."""
    if not returns:
        return 0.0
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


def compute_metrics(rows: list[DecisionRow]) -> dict[str, Any]:
    """Aggregate journal rows into the dashboard's metric payload.

    Per-mode buckets: shadow / paper / live. Each has the same shape.
    A separate ``aggregate`` bucket includes paper + live (realised
    fills only — shadow has no PnL by definition).
    """
    by_mode: dict[str, list[DecisionRow]] = defaultdict(list)
    for r in rows:
        by_mode[r.mode].append(r)

    def _bucket(rs: list[DecisionRow]) -> dict[str, Any]:
        n_decisions = len(rs)
        n_accepted = sum(1 for r in rs if r.accepted)
        n_rejected = n_decisions - n_accepted
        fills_with_pnl = [r for r in rs if r.accepted and r.pnl_usd is not None]
        per_bet_pnl = [r.pnl_usd for r in fills_with_pnl]
        per_bet_notional = [r.notional_usd for r in fills_with_pnl if r.notional_usd]
        per_bet_returns = [
            (pnl / notl) for pnl, notl in zip(per_bet_pnl, per_bet_notional, strict=False)
            if notl and notl > 0
        ]
        total_pnl = sum(per_bet_pnl) if per_bet_pnl else 0.0
        total_notional = sum(per_bet_notional) if per_bet_notional else 0.0
        wins = sum(1 for p in per_bet_pnl if p > 0)
        sharpe = _per_bet_sharpe_ann(per_bet_returns)
        return {
            "n_decisions": n_decisions,
            "n_accepted": n_accepted,
            "n_rejected": n_rejected,
            "n_fills_with_pnl": len(fills_with_pnl),
            "total_pnl_usd": total_pnl,
            "total_notional_usd": total_notional,
            "win_rate": (wins / len(per_bet_pnl)) if per_bet_pnl else None,
            "per_bet_sharpe_ann": sharpe,
            "max_drawdown_usd": _max_drawdown(per_bet_pnl),
            "rejection_reasons": _top_reasons(rs),
        }

    by_alpha: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "accepted": 0})
    for r in rows:
        by_alpha[r.alpha]["n"] += 1
        if r.accepted:
            by_alpha[r.alpha]["accepted"] += 1

    aggregate_realised = [r for r in rows if r.mode in ("paper", "live")
                          and r.accepted and r.pnl_usd is not None]
    aggregate = _bucket(aggregate_realised) if aggregate_realised else _bucket([])

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_decisions_total": len(rows),
        "by_mode": {m: _bucket(rs) for m, rs in by_mode.items()},
        "by_alpha": dict(by_alpha),
        "aggregate_paper_plus_live": aggregate,
        "last_decision_utc": rows[-1].timestamp if rows else None,
    }


def _top_reasons(rs: list[DecisionRow], top_k: int = 5) -> list[dict[str, Any]]:
    counter: dict[str, int] = defaultdict(int)
    for r in rs:
        if not r.accepted and r.rejection_reason:
            counter[r.rejection_reason] += 1
    items = sorted(counter.items(), key=lambda x: -x[1])[:top_k]
    return [{"reason": k, "count": v} for k, v in items]


def recent_decisions(rows: list[DecisionRow], limit: int = 50) -> list[dict[str, Any]]:
    """Tail of the journal, formatted for the decisions table in the UI."""
    tail = rows[-limit:][::-1]   # newest first
    return [
        {
            "timestamp": r.timestamp,
            "alpha": r.alpha,
            "mode": r.mode,
            "side": r.side,
            "accepted": r.accepted,
            "rejection_reason": r.rejection_reason,
            "size": r.requested_size,
            "price": r.requested_price,
            "notional_usd": r.notional_usd,
            "expected_fill_price": r.expected_fill_price,
            "expected_slippage_bps": r.expected_slippage_bps,
            "pnl_usd": r.pnl_usd,
            "token_id": r.token_id[:12] + "…" if len(r.token_id) > 12 else r.token_id,
        }
        for r in tail
    ]
