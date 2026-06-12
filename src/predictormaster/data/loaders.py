"""High-level real-data loader the dashboard consumes.

Returns a ``MatchFrame``-shaped object (matches dataframe + per-team
empirical strength index) populated from real public APIs:

  nba/nfl/ncaaf/ncaab → ESPN scoreboard (no key)
  mlb                 → MLB Stats API (no key)
  nhl                 → NHL public schedule (no key)
  epl                 → football-data.co.uk historical CSVs (no key)

All HTTP goes through ``data.cache.HTTPCache`` so a 180-day backtest is
cached after the first fetch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .cache import HTTPCache
from .ingestion.sports import epl, espn, mlb, nhl

SPORTS = ("nba", "nfl", "mlb", "nhl", "epl", "ncaaf", "ncaab")


@dataclass(frozen=True)
class MatchFrame:
    sport: str
    matches: pd.DataFrame      # date, home, away, home_score, away_score, [moneyline_home, moneyline_away, spread_home, total]
    strengths: pd.DataFrame    # date x team — empirical rolling strength
    source: str                # human-readable provenance


def _fetch_games(sport: str, start: date, end: date, cache: HTTPCache | None) -> tuple[list[espn.Game], str]:
    if sport in ("nba", "nfl", "ncaaf", "ncaab"):
        return espn.fetch_games(sport, start, end, cache=cache), f"ESPN scoreboard ({sport.upper()})"
    if sport == "mlb":
        return mlb.fetch_games(start, end, cache=cache), "MLB Stats API"
    if sport == "nhl":
        return nhl.fetch_games(start, end, cache=cache), "NHL public schedule"
    if sport == "epl":
        return epl.fetch_games(start, end, cache=cache), "football-data.co.uk"
    raise ValueError(f"unsupported sport {sport!r}; choose one of {SPORTS}")


def _empirical_strength(matches: pd.DataFrame, *, halflife: int = 10) -> pd.DataFrame:
    """Per-team rolling exponential mean of (points_for - points_against),
    indexed by match date. This is the honest 'reference signal' the Kalman
    posterior is benchmarked against — it is *not* a true latent state."""
    if matches.empty:
        return pd.DataFrame()
    long = pd.concat([
        matches.assign(team=matches["home"], diff=matches["home_score"] - matches["away_score"]),
        matches.assign(team=matches["away"], diff=matches["away_score"] - matches["home_score"]),
    ])[["date", "team", "diff"]].dropna()
    long = long.sort_values("date")
    pivot = long.pivot_table(index="date", columns="team", values="diff", aggfunc="mean")
    if pivot.empty:
        return pivot
    smoothed = pivot.ewm(halflife=halflife, ignore_na=True).mean()
    smoothed = smoothed.ffill().fillna(0.0)
    return smoothed


def load_matches(sport: str, start: date, end: date, *, cache: HTTPCache | None = None) -> MatchFrame:
    games, source = _fetch_games(sport, start, end, cache)
    rows = []
    for g in games:
        if g.home_score is None or g.away_score is None or not g.completed:
            continue
        rows.append({
            "date": pd.Timestamp(g.start_utc).normalize(),
            "home": g.home,
            "away": g.away,
            "home_score": float(g.home_score),
            "away_score": float(g.away_score),
            "moneyline_home": g.moneyline_home,
            "moneyline_away": g.moneyline_away,
            "spread_home": g.spread_home,
            "total": g.total,
            "event_id": g.event_id,
        })
    matches = pd.DataFrame(rows)
    if not matches.empty:
        matches = matches.sort_values("date").reset_index(drop=True)
    strengths = _empirical_strength(matches)
    if not strengths.empty:
        idx = pd.date_range(matches["date"].min(), matches["date"].max(), freq="D")
        strengths = strengths.reindex(idx).ffill().fillna(0.0)
    # Backwards-compat columns the old dashboard expects.
    matches["true_strength_home"] = np.nan
    matches["true_strength_away"] = np.nan
    return MatchFrame(sport=sport, matches=matches, strengths=strengths, source=source)
