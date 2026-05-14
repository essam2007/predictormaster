"""α3-daily evaluator: sentiment-conditioned EPL outcome forecasting.

Honest framing
--------------
This is NOT the true α3 sentiment-shock alpha (which requires intra-
day book snapshots to capture decay over a 30-minute window). It is a
daily-frequency proxy that asks a related question: does relative
GDELT news-tone movement, properly z-scored, predict the home-win
outcome at non-zero edge against the bookmaker's closing line?

If the answer is "yes" with all stress-test gates passing, that's a
candidate alpha. If the answer is "no" after a fair evolutionary
search, the methodology is validated and we know not to bother
porting the same hyperparameters to intra-day data later.

Data sources (all real, all public)
-----------------------------------
  - EPL match results + closing odds: football-data.co.uk
    (via predictormaster.data.loaders.load_matches("epl", ...))
  - News-tone time series: GDELT 2.0 DOC API TimelineTone
    (via predictormaster.data.enrichment.gdelt.fetch_team_tone)

No synthetic data anywhere. Where GDELT has no coverage, the match
is skipped (not imputed) — consistent with the project's "NaN where
missing, never fabricate" rule.

Split convention
----------------
``train`` = first 70% of matches by date.
``holdout`` = last 30%. The evolution loop only ever sees ``train``.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ...data.cache import HTTPCache, default_cache
from ...data.enrichment.gdelt import fetch_team_tone
from ..fitness import EvaluationResult
from ..genome import Genome

logger = logging.getLogger(__name__)


@dataclass
class SentimentDailyEvaluator:
    """One evaluator instance covers one (sport, date-range) experiment.

    GDELT tone is fetched ONCE per team at construction time and
    cached on the instance so all 120-odd genome evaluations share
    the same network IO.
    """
    matches: pd.DataFrame                  # date, home, away, home_score, away_score, moneyline_home, moneyline_away
    tone_by_team: dict[str, pd.Series]     # team → daily tone Series
    train_cutoff: pd.Timestamp
    bets_per_year: int = 200
    _cache: HTTPCache | None = None
    _team_match_index: dict[str, list[int]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        # Build a fast (team → row indices) lookup so we don't scan
        # the full match table for each team's GDELT context.
        for i, r in self.matches.iterrows():
            self._team_match_index.setdefault(r["home"], []).append(int(i))
            self._team_match_index.setdefault(r["away"], []).append(int(i))

    # ---------------- public API ----------------

    def evaluate(self, genome: Genome, *, split: str) -> EvaluationResult:
        if split not in ("train", "holdout"):
            raise ValueError(f"unknown split {split!r}")
        v = genome.values
        sub = self._split(split)
        if sub.empty:
            return EvaluationResult(genome=genome, per_bet_returns=np.array([]),
                                    n_bets=0, notes=("empty split",))

        rets: list[float] = []
        for _, row in sub.iterrows():
            r = self._bet_for_match(row, v)
            if r is not None:
                rets.append(r)
        arr = np.array(rets, dtype=float)
        return EvaluationResult(
            genome=genome,
            per_bet_returns=arr,
            n_bets=arr.size,
            notes=() if arr.size else ("no bets matched filters",),
        )

    # ---------------- internals ----------------

    def _split(self, name: str) -> pd.DataFrame:
        if name == "train":
            return self.matches[self.matches["date"] < self.train_cutoff]
        return self.matches[self.matches["date"] >= self.train_cutoff]

    def _signal(
        self,
        team: str,
        as_of: pd.Timestamp,
        lookback_days: int,
        half_life_days: int,
        min_obs: int,
    ) -> float | None:
        """Decay-weighted (polarity-now − mean) / sd z-score for one team."""
        s = self.tone_by_team.get(team)
        if s is None or s.empty:
            return None
        # GDELT index is tz-naive; coerce as_of to match so the
        # comparison doesn't blow up on tz-aware match timestamps.
        as_of_naive = as_of.tz_localize(None) if as_of.tzinfo is not None else as_of
        lo = (as_of_naive - pd.Timedelta(days=lookback_days)).normalize()
        hi = as_of_naive.normalize()
        win = s.loc[(s.index >= lo) & (s.index < hi)].dropna()
        if win.size < min_obs:
            return None
        ages = (hi - win.index).days.to_numpy(dtype=float)
        w = 0.5 ** (ages / max(half_life_days, 1))
        if w.sum() <= 0:
            return None
        p = win.to_numpy(dtype=float)
        mu = float(np.sum(w * p) / np.sum(w))
        var = float(np.sum(w * (p - mu) ** 2) / np.sum(w))
        sd = math.sqrt(max(var, 1e-9))
        if sd <= 1e-9:
            return None
        p_now = float(p[-1])
        return (p_now - mu) / sd

    def _bet_for_match(self, row: pd.Series, v: dict) -> float | None:
        z_home = self._signal(
            row["home"], pd.Timestamp(row["date"]),
            lookback_days=int(v["sentiment_lookback_days"]),
            half_life_days=int(v["half_life_days"]),
            min_obs=int(v["min_observations"]),
        )
        z_away = self._signal(
            row["away"], pd.Timestamp(row["date"]),
            lookback_days=int(v["sentiment_lookback_days"]),
            half_life_days=int(v["half_life_days"]),
            min_obs=int(v["min_observations"]),
        )
        if z_home is None or z_away is None:
            return None
        diff = z_home - z_away
        if abs(diff) < float(v["z_threshold"]):
            return None

        oh = row.get("moneyline_home")
        oa = row.get("moneyline_away")
        if oh is None or oa is None or not np.isfinite(oh) or not np.isfinite(oa):
            return None
        if oh <= 1.0 or oa <= 1.0:
            return None
        p_home = 1.0 / float(oh)        # bookmaker's home-win implied prob
        p_away = 1.0 / float(oa)
        if not (float(v["market_p_lo"]) <= p_home <= float(v["market_p_hi"])):
            return None

        favorable_home = diff > 0
        # side="favorable" bets WITH sentiment; "contrarian" fades it
        bet_home = favorable_home if v["side"] == "favorable" else not favorable_home

        # bet_against_market: only fire when sentiment-side disagrees
        # with the bookmaker's favorite. If sentiment side matches the
        # favorite the bet would be "consensus", which is what the
        # closing line already prices in.
        if bool(v.get("bet_against_market", False)):
            market_favorite_home = p_home > p_away
            sentiment_picks_home = bet_home
            if market_favorite_home == sentiment_picks_home:
                return None

        home_win = float(row["home_score"]) > float(row["away_score"])
        if bet_home:
            outcome = 1.0 if home_win else 0.0
            entry = p_home
        else:
            outcome = 0.0 if home_win else 1.0     # bet "away win"; pays if home loses (incl. draws)
            entry = p_away
        if entry <= 0:
            return None
        return (outcome - entry) / entry          # binary-market return


def build_sentiment_daily_evaluator(
    start: date,
    end: date,
    *,
    train_fraction: float = 0.70,
    cache: HTTPCache | None = None,
) -> SentimentDailyEvaluator:
    """Construct an evaluator pre-loaded with EPL matches + GDELT tones.

    GDELT calls are cached on disk by ``HTTPCache`` — first construction
    can take ~30s per team × ~40 teams; subsequent runs reuse the cache.
    """
    from ...data.loaders import load_matches  # local import — heavy module

    c = cache or default_cache()
    mf = load_matches("epl", start, end, cache=c)
    matches = mf.matches.copy()
    if matches.empty:
        raise RuntimeError("no EPL matches in date range; cannot build evaluator")
    matches = matches.sort_values("date").reset_index(drop=True)
    cutoff_i = int(len(matches) * train_fraction)
    cutoff = pd.Timestamp(matches.iloc[cutoff_i]["date"])

    teams = sorted(set(matches["home"]) | set(matches["away"]))
    span_start = matches["date"].min().date() - timedelta(days=30)
    span_end = matches["date"].max().date() + timedelta(days=2)
    tones: dict[str, pd.Series] = {}
    for t in teams:
        try:
            tones[t] = fetch_team_tone(t, span_start, span_end, cache=c)
        except Exception as e:                    # pragma: no cover — network flake
            logger.warning("GDELT fetch failed for %s: %s", t, e)
            tones[t] = pd.Series(dtype=float)

    return SentimentDailyEvaluator(
        matches=matches, tone_by_team=tones, train_cutoff=cutoff, _cache=c,
    )
