"""Per-bucket performance metrics: hit-rate, average R, expectancy, equity curve."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.trades import Trade
from .buckets import BUCKETS


@dataclass
class BucketStats:
    label: str
    n: int = 0
    wins: int = 0
    sum_r: float = 0.0
    sum_pnl: float = 0.0
    r_values: list[float] = field(default_factory=list)

    def add(self, t: Trade) -> None:
        self.n += 1
        if t.realized_r > 0:
            self.wins += 1
        self.sum_r += t.realized_r
        self.sum_pnl += t.realized_pnl
        self.r_values.append(t.realized_r)

    @property
    def hit_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def avg_r(self) -> float:
        return self.sum_r / self.n if self.n else 0.0

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "n": self.n,
            "hit_rate": round(self.hit_rate, 3),
            "avg_r": round(self.avg_r, 3),
            "total_pnl": round(self.sum_pnl, 2),
        }


def summarize(trades: list[Trade]) -> dict:
    """Overall stats plus a breakdown for every bucket dimension."""
    closed = [t for t in trades if not t.is_open]
    overall = _overall(closed)
    breakdown: dict[str, list[dict]] = {}
    for dim, fn in BUCKETS.items():
        groups: dict[str, BucketStats] = {}
        for t in closed:
            label = fn(t)
            groups.setdefault(label, BucketStats(label)).add(t)
        breakdown[dim] = [g.as_dict() for g in sorted(groups.values(), key=lambda s: s.label)]
    return {"overall": overall, "buckets": breakdown}


def _overall(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "hit_rate": 0.0, "avg_r": 0.0, "expectancy_r": 0.0,
                "profit_factor": 0.0, "total_pnl": 0.0}
    wins = [t for t in trades if t.realized_r > 0]
    losses = [t for t in trades if t.realized_r <= 0]
    gross_win = sum(t.realized_pnl for t in wins)
    gross_loss = -sum(t.realized_pnl for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    avg_r = sum(t.realized_r for t in trades) / n
    return {
        "n": n,
        "hit_rate": round(len(wins) / n, 3),
        "avg_r": round(avg_r, 3),
        "expectancy_r": round(avg_r, 3),
        "profit_factor": round(pf, 3) if pf != float("inf") else None,
        "total_pnl": round(sum(t.realized_pnl for t in trades), 2),
    }


def equity_curve(trades: list[Trade]) -> list[dict]:
    """Cumulative PnL/R over closed trades in time order."""
    closed = sorted((t for t in trades if not t.is_open), key=lambda t: t.exit_ts or t.entry_ts)
    cum_pnl = 0.0
    cum_r = 0.0
    out = []
    for t in closed:
        cum_pnl += t.realized_pnl
        cum_r += t.realized_r
        out.append({"ts": (t.exit_ts or t.entry_ts).isoformat(),
                    "cum_pnl": round(cum_pnl, 2), "cum_r": round(cum_r, 3)})
    return out
