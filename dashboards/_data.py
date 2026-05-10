"""Deterministic synthetic match data per (sport, date range, seed).

The generator is intentionally simple but calibrated per sport: latent team
strengths follow an Ornstein-Uhlenbeck process (matches the platform's OU
spec in docs/derivations/ou_strength.md), and per-match scores are drawn
from sport-appropriate distributions:

* nba / nfl: Normal(mu, sigma) per team, sigma per league.
* epl / soccer / mlb / nhl: Poisson(lambda) per team.

Swap in a real loader by replacing ``generate_matches`` with a function that
returns the same MatchFrame dataclass — the dashboards do not care where the
data came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SPORTS = ("nba", "nfl", "epl", "mlb", "nhl")

_TEAMS = {
    "nba": ["Lakers", "Warriors", "Celtics", "Heat", "Bucks", "Nuggets",
            "Suns", "76ers", "Mavericks", "Nets", "Clippers", "Knicks"],
    "nfl": ["Chiefs", "Bills", "Eagles", "49ers", "Cowboys", "Bengals",
            "Ravens", "Lions", "Dolphins", "Packers", "Vikings", "Jets"],
    "epl": ["Arsenal", "Man City", "Liverpool", "Chelsea", "Tottenham",
            "Man United", "Newcastle", "Brighton", "Aston Villa", "West Ham"],
    "mlb": ["Dodgers", "Yankees", "Astros", "Braves", "Phillies",
            "Rangers", "Orioles", "Mets", "Padres", "Cubs"],
    "nhl": ["Avalanche", "Rangers", "Bruins", "Oilers", "Hurricanes",
            "Maple Leafs", "Stars", "Panthers", "Devils", "Kings"],
}

_SCORING = {
    "nba": {"kind": "normal", "mu": 112.0, "sigma": 11.0, "edge_per_strength": 5.0},
    "nfl": {"kind": "normal", "mu": 23.0, "sigma": 8.0, "edge_per_strength": 4.0},
    "epl": {"kind": "poisson", "lam": 1.4, "edge_per_strength": 0.6},
    "mlb": {"kind": "poisson", "lam": 4.5, "edge_per_strength": 0.8},
    "nhl": {"kind": "poisson", "lam": 3.1, "edge_per_strength": 0.7},
}

_GAMES_PER_WEEK = {"nba": 3, "nfl": 1, "epl": 1, "mlb": 5, "nhl": 3}


@dataclass(frozen=True)
class MatchFrame:
    sport: str
    matches: pd.DataFrame  # date, home, away, home_score, away_score, true_strength_home, true_strength_away
    strengths: pd.DataFrame  # date x team — true latent strengths


def _ou_strengths(
    n_days: int, teams: list[str], rng: np.random.Generator,
    *, theta: float = 0.05, mu: float = 0.0, sigma: float = 0.15,
) -> pd.DataFrame:
    n_teams = len(teams)
    x = rng.normal(0.0, 0.5, size=n_teams)
    series = np.zeros((n_days, n_teams))
    for t in range(n_days):
        x = x + theta * (mu - x) + sigma * rng.standard_normal(n_teams)
        series[t] = x
    return pd.DataFrame(series, columns=teams)


def generate_matches(sport: str, start: date, end: date, *, seed: int = 0) -> MatchFrame:
    if sport not in _TEAMS:
        raise ValueError(f"unknown sport {sport!r}; choose one of {SPORTS}")
    if end <= start:
        raise ValueError("end must be after start")

    rng = np.random.default_rng(seed)
    teams = list(_TEAMS[sport])
    n_days = (end - start).days
    strengths = _ou_strengths(n_days, teams, rng)
    strengths.index = pd.to_datetime([start + timedelta(days=i) for i in range(n_days)])

    cfg = _SCORING[sport]
    n_per_week = _GAMES_PER_WEEK[sport]
    schedule_dates = pd.date_range(start, end - timedelta(days=1), freq="D")
    rows = []
    for d in schedule_dates:
        if rng.random() > n_per_week / 7.0:
            continue
        # one or two matches per matchday
        for _ in range(rng.integers(1, 3)):
            i, j = rng.choice(len(teams), size=2, replace=False)
            home, away = teams[i], teams[j]
            sh = strengths.loc[d, home]
            sa = strengths.loc[d, away]
            edge = cfg["edge_per_strength"] * (sh - sa)
            if cfg["kind"] == "normal":
                hs = rng.normal(cfg["mu"] + edge, cfg["sigma"])
                as_ = rng.normal(cfg["mu"] - edge, cfg["sigma"])
                home_score = max(0.0, hs)
                away_score = max(0.0, as_)
            else:
                lam_h = max(0.05, cfg["lam"] + edge)
                lam_a = max(0.05, cfg["lam"] - edge)
                home_score = float(rng.poisson(lam_h))
                away_score = float(rng.poisson(lam_a))
            rows.append({
                "date": d, "home": home, "away": away,
                "home_score": home_score, "away_score": away_score,
                "true_strength_home": float(sh), "true_strength_away": float(sa),
            })
    matches = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return MatchFrame(sport=sport, matches=matches, strengths=strengths)


@dataclass(frozen=True)
class FilterTrace:
    teams: list[str]
    timestamps: pd.DatetimeIndex
    posterior_mean: np.ndarray   # T x n_teams
    posterior_var: np.ndarray    # T x n_teams (diag of P)
    innovation: np.ndarray       # T x n_teams
    kalman_gain_diag: np.ndarray  # T x n_teams (diag of K)


def run_kalman(mf: MatchFrame, *, q: float, r: float) -> FilterTrace:
    """Run the platform's KalmanFilter on per-day score-margin observations."""
    from predictormaster.models.kalman import team_strength_filter

    teams = list(mf.strengths.columns)
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    kf = team_strength_filter(n, q=q, r=r)

    days = sorted(mf.matches["date"].unique())
    T = len(days)
    means = np.zeros((T, n))
    vars_ = np.zeros((T, n))
    innovs = np.zeros((T, n))
    gains = np.zeros((T, n))

    for t, d in enumerate(days):
        kf.predict()
        day_matches = mf.matches[mf.matches["date"] == d]
        y = kf.x.copy()  # default observation = prior, so unobserved teams aren't pulled
        seen = np.zeros(n, dtype=bool)
        for _, row in day_matches.iterrows():
            i, j = idx[row["home"]], idx[row["away"]]
            margin = row["home_score"] - row["away_score"]
            scale = 1.0 if mf.sport in {"epl", "mlb", "nhl"} else 10.0
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
    bets: pd.DataFrame  # per-bet pnl, edge, stake
    equity: pd.Series
    sharpe: float
    sortino: float
    max_drawdown: float
    win_rate: float
    n_bets: int


def _logistic(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-x))


def simulate_strategy(
    mf: MatchFrame,
    trace: FilterTrace,
    *,
    edge_threshold: float = 0.03,
    bet_fraction: float = 0.02,
    bookmaker_juice: float = 0.05,
    seed: int = 1,
) -> StrategyResult:
    """Bet whenever the Kalman-implied home-win probability differs from a
    noisier 'market' price by more than ``edge_threshold``. Stakes are a flat
    fraction of bankroll. Returns equity curve, Sharpe, Sortino, and max DD.
    """
    rng = np.random.default_rng(seed)
    teams = trace.teams
    idx = {t: i for i, t in enumerate(teams)}
    day_to_t = {d: i for i, d in enumerate(trace.timestamps)}

    cfg = _SCORING[mf.sport]
    rows = []
    bankroll = 1.0
    equity = []
    dates = []

    for _, row in mf.matches.iterrows():
        d = row["date"]
        t = day_to_t.get(d)
        if t is None or t < 5:
            continue
        i, j = idx[row["home"]], idx[row["away"]]
        prior_strength = trace.posterior_mean[t - 1, i] - trace.posterior_mean[t - 1, j]
        edge_signal = cfg["edge_per_strength"] * prior_strength
        if cfg["kind"] == "normal":
            p_home = float(_logistic(edge_signal / cfg["sigma"]))
        else:
            p_home = float(_logistic(edge_signal))

        # Synthetic market price: true probability + bookmaker juice + noise.
        true_edge = cfg["edge_per_strength"] * (row["true_strength_home"] - row["true_strength_away"])
        if cfg["kind"] == "normal":
            true_p = float(_logistic(true_edge / cfg["sigma"]))
        else:
            true_p = float(_logistic(true_edge))
        market_p = np.clip(true_p + rng.normal(0, 0.05) + bookmaker_juice * 0.5, 0.02, 0.98)

        edge = p_home - market_p
        if abs(edge) < edge_threshold:
            equity.append(bankroll)
            dates.append(d)
            continue

        side = "home" if edge > 0 else "away"
        won = row["home_score"] > row["away_score"] if side == "home" else row["home_score"] < row["away_score"]
        # Decimal odds derived from market (with juice baked in).
        market_used = market_p if side == "home" else (1 - market_p)
        odds = (1.0 / market_used) * (1.0 - bookmaker_juice)
        stake = bet_fraction * bankroll
        pnl = stake * (odds - 1.0) if won else -stake
        bankroll += pnl
        rows.append({
            "date": d, "home": row["home"], "away": row["away"], "side": side,
            "edge": edge, "stake": stake, "odds": odds, "won": bool(won), "pnl": pnl,
            "bankroll": bankroll,
        })
        equity.append(bankroll)
        dates.append(d)

    bets = pd.DataFrame(rows)
    eq = pd.Series(equity, index=pd.DatetimeIndex(dates), name="equity").groupby(level=0).last()
    if len(bets) < 2:
        return StrategyResult(bets=bets, equity=eq, sharpe=0.0, sortino=0.0,
                              max_drawdown=0.0, win_rate=0.0, n_bets=len(bets))
    daily_ret = eq.pct_change().dropna()
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-12) * np.sqrt(252))
    downside = daily_ret[daily_ret < 0].std()
    sortino = float(daily_ret.mean() / (downside + 1e-12) * np.sqrt(252))
    running_max = eq.cummax()
    max_dd = float((eq / running_max - 1.0).min())
    win_rate = float(bets["won"].mean())
    return StrategyResult(
        bets=bets, equity=eq, sharpe=sharpe, sortino=sortino,
        max_drawdown=max_dd, win_rate=win_rate, n_bets=len(bets),
    )
