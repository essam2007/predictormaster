"""Dashboard data layer — real public APIs, no synthetic generation.

Public surface kept stable so dashboards/strategy.py is untouched:

  SPORTS                         tuple[str, ...]
  generate_matches(sport, start, end, *, seed=0) -> MatchFrame
      Now a real-data loader. ``seed`` is accepted for backwards-compat
      with the old Streamlit signature but is ignored — there is no
      randomness when reading historical games.
  run_kalman(mf, *, q, r)        -> FilterTrace
  simulate_strategy(...)         -> StrategyResult
      Bets at the *actual* moneyline odds where the data source provides
      them (EPL: closing Bet365/Pinnacle/etc. averaged; NFL/NBA/NCAA:
      ESPN-published consensus). Where odds are missing the bet is
      skipped — no synthetic market prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from predictormaster.data.loaders import SPORTS as _SPORTS
from predictormaster.data.loaders import MatchFrame, load_matches
from predictormaster.models.kalman import team_strength_filter

SPORTS = _SPORTS

# Keep MatchFrame importable here for any caller that imports from dashboards._data.
MatchFrame = MatchFrame  # noqa: PLW0127  (re-export)


def generate_matches(sport: str, start: date, end: date, *, seed: int = 0) -> MatchFrame:
    """Real public-API loader. ``seed`` accepted for signature parity."""
    return load_matches(sport, start, end)


@dataclass(frozen=True)
class FilterTrace:
    teams: list[str]
    timestamps: pd.DatetimeIndex
    posterior_mean: np.ndarray   # T x n_teams
    posterior_var: np.ndarray    # T x n_teams (diag of P)
    innovation: np.ndarray       # T x n_teams
    kalman_gain_diag: np.ndarray  # T x n_teams (diag of K)


def _team_universe(mf: MatchFrame) -> list[str]:
    if not mf.strengths.empty:
        return list(mf.strengths.columns)
    if mf.matches.empty:
        return []
    return sorted(set(mf.matches["home"]) | set(mf.matches["away"]))


def _obs_scale(sport: str) -> float:
    return 1.0 if sport in {"epl", "mlb", "nhl"} else 10.0


def run_kalman(mf: MatchFrame, *, q: float, r: float) -> FilterTrace:
    teams = _team_universe(mf)
    if not teams or mf.matches.empty:
        empty = np.zeros((0, max(len(teams), 1)))
        return FilterTrace(
            teams=teams,
            timestamps=pd.DatetimeIndex([]),
            posterior_mean=empty, posterior_var=empty,
            innovation=empty, kalman_gain_diag=empty,
        )
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    kf = team_strength_filter(n, q=q, r=r)
    days = sorted(mf.matches["date"].unique())
    T = len(days)
    means = np.zeros((T, n))
    vars_ = np.zeros((T, n))
    innovs = np.zeros((T, n))
    gains = np.zeros((T, n))
    scale = _obs_scale(mf.sport)
    for t, d in enumerate(days):
        kf.predict()
        day_matches = mf.matches[mf.matches["date"] == d]
        y = kf.x.copy()
        seen = np.zeros(n, dtype=bool)
        for _, row in day_matches.iterrows():
            i, j = idx.get(row["home"]), idx.get(row["away"])
            if i is None or j is None:
                continue
            margin = row["home_score"] - row["away_score"]
            obs = margin / scale
            y[i] = obs / 2.0
            y[j] = -obs / 2.0
            seen[i] = seen[j] = True
        prior_mean = kf.x.copy()
        S = kf.H @ kf.P @ kf.H.T + kf.R
        K = kf.P @ kf.H.T @ np.linalg.inv(S)
        kf.update(y)
        means[t] = kf.x
        vars_[t] = np.diag(kf.P)
        innovs[t] = (y - prior_mean) * seen
        gains[t] = np.diag(K)
    return FilterTrace(
        teams=teams,
        timestamps=pd.DatetimeIndex(days),
        posterior_mean=means,
        posterior_var=vars_,
        innovation=innovs,
        kalman_gain_diag=gains,
    )


@dataclass(frozen=True)
class StrategyResult:
    bets: pd.DataFrame
    equity: pd.Series
    sharpe: float
    sortino: float
    max_drawdown: float
    win_rate: float
    n_bets: int
    closing_line_value: float
    note: str


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def _american_to_decimal(ml: float) -> float:
    if ml > 0:
        return 1.0 + ml / 100.0
    return 1.0 + 100.0 / abs(ml)


def _to_decimal(value: float | None, sport: str) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    if sport == "epl":
        return float(value) if value > 1.0 else None
    return _american_to_decimal(float(value))


def _devig(p_home: float, p_away: float) -> tuple[float, float]:
    s = p_home + p_away
    if s <= 0:
        return p_home, p_away
    return p_home / s, p_away / s


def simulate_strategy(
    mf: MatchFrame,
    trace: FilterTrace,
    *,
    edge_threshold: float = 0.03,
    bet_fraction: float = 0.02,
    bookmaker_juice: float = 0.0,  # accepted for signature parity; real juice comes from the data
    seed: int = 1,
) -> StrategyResult:
    if mf.matches.empty or len(trace.teams) == 0:
        empty = pd.DataFrame()
        return StrategyResult(
            bets=empty, equity=pd.Series(dtype=float),
            sharpe=0.0, sortino=0.0, max_drawdown=0.0, win_rate=0.0,
            n_bets=0, closing_line_value=0.0,
            note="no completed matches in range",
        )
    teams = trace.teams
    idx = {t: i for i, t in enumerate(teams)}
    day_to_t = {d: i for i, d in enumerate(trace.timestamps)}

    # Heuristic margin scale per sport for the model probability map.
    sigma_map = {"nba": 11.0, "nfl": 8.0, "ncaaf": 12.0, "ncaab": 9.0,
                 "mlb": 3.0, "nhl": 1.6, "epl": 1.3}
    sigma = sigma_map.get(mf.sport, 5.0)

    rows = []
    bankroll = 1.0
    equity = []
    dates = []
    skipped_no_odds = 0

    for _, row in mf.matches.iterrows():
        d = row["date"]
        t = day_to_t.get(d)
        if t is None or t < 5:
            continue
        i, j = idx.get(row["home"]), idx.get(row["away"])
        if i is None or j is None:
            continue
        margin_pred = (trace.posterior_mean[t - 1, i] - trace.posterior_mean[t - 1, j]) * _obs_scale(mf.sport)
        p_home_model = float(_logistic(margin_pred / sigma))

        dec_home = _to_decimal(row.get("moneyline_home"), mf.sport)
        dec_away = _to_decimal(row.get("moneyline_away"), mf.sport)
        if dec_home is None or dec_away is None:
            skipped_no_odds += 1
            equity.append(bankroll)
            dates.append(d)
            continue

        raw_p_home = 1.0 / dec_home
        raw_p_away = 1.0 / dec_away
        market_home, market_away = _devig(raw_p_home, raw_p_away)
        edge_home = p_home_model - market_home
        edge_away = (1.0 - p_home_model) - market_away

        if max(abs(edge_home), abs(edge_away)) < edge_threshold:
            equity.append(bankroll)
            dates.append(d)
            continue

        if edge_home >= edge_away:
            side = "home"
            edge = edge_home
            dec = dec_home
            market_p = market_home
            won = row["home_score"] > row["away_score"]
        else:
            side = "away"
            edge = edge_away
            dec = dec_away
            market_p = market_away
            won = row["away_score"] > row["home_score"]

        stake = bet_fraction * bankroll
        pnl = stake * (dec - 1.0) if won else -stake
        bankroll += pnl
        rows.append({
            "date": d, "home": row["home"], "away": row["away"], "side": side,
            "edge": edge, "stake": stake, "odds": dec,
            "market_p": market_p, "model_p": p_home_model if side == "home" else 1 - p_home_model,
            "won": bool(won), "pnl": pnl, "bankroll": bankroll,
        })
        equity.append(bankroll)
        dates.append(d)

    bets = pd.DataFrame(rows)
    eq = pd.Series(equity, index=pd.DatetimeIndex(dates), name="equity").groupby(level=0).last()
    note_parts = [f"source: {mf.source}"]
    if skipped_no_odds:
        note_parts.append(f"skipped {skipped_no_odds} games with no odds in the free feed")
    note = "; ".join(note_parts)
    if len(bets) < 2:
        return StrategyResult(
            bets=bets, equity=eq, sharpe=0.0, sortino=0.0, max_drawdown=0.0,
            win_rate=0.0, n_bets=len(bets), closing_line_value=0.0, note=note,
        )
    daily_ret = eq.pct_change().dropna()
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-12) * np.sqrt(252))
    downside = daily_ret[daily_ret < 0].std()
    sortino = float(daily_ret.mean() / (downside + 1e-12) * np.sqrt(252))
    running_max = eq.cummax()
    max_dd = float((eq / running_max - 1.0).min())
    win_rate = float(bets["won"].mean())
    clv = float((bets["model_p"] - bets["market_p"]).mean())
    return StrategyResult(
        bets=bets, equity=eq, sharpe=sharpe, sortino=sortino,
        max_drawdown=max_dd, win_rate=win_rate, n_bets=len(bets),
        closing_line_value=clv, note=note,
    )
