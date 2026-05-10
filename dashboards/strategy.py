"""Streamlit dashboard: data, normal distributions, Kalman filter, and
strategy / Sharpe ratio — keyed on (sport, date range).

Launch:
    pip install -e ".[dashboard]"
    streamlit run dashboards/strategy.py
"""
import sys
from pathlib import Path

# Ensure the project root is on sys.path regardless of how Streamlit
# was invoked. Streamlit inserts the script's own directory, not the
# project root, so absolute imports like `from dashboards._data import`
# would otherwise fail.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from scipy import stats

from dashboards._data import (
    SPORTS,
    generate_matches,
    run_kalman,
    simulate_strategy,
)

st.set_page_config(page_title="predictormaster — strategy lab", layout="wide")
st.title("predictormaster strategy lab")

with st.sidebar:
    st.header("Dataset")
    sport = st.selectbox("Sport", SPORTS, index=0)
    today = date.today()
    default_start = today - timedelta(days=180)
    start = st.date_input("Start date", default_start, max_value=today - timedelta(days=14))
    end = st.date_input("End date", today, min_value=start + timedelta(days=14))
    seed = st.number_input("Random seed", value=0, step=1)

    st.header("Kalman filter")
    q = st.slider("Process noise Q", 0.001, 0.5, 0.01, step=0.001, format="%.3f")
    r = st.slider("Observation noise R", 0.05, 5.0, 0.5, step=0.05)

    st.header("Strategy")
    edge_threshold = st.slider("Min edge to bet", 0.0, 0.20, 0.03, step=0.005)
    bet_fraction = st.slider("Stake (fraction of bankroll)", 0.001, 0.10, 0.02, step=0.001, format="%.3f")
    juice = st.slider("Bookmaker juice", 0.0, 0.10, 0.05, step=0.005)


@st.cache_data(show_spinner=False)
def _load(sport: str, start: date, end: date, seed: int):
    return generate_matches(sport, start, end, seed=seed)


@st.cache_data(show_spinner=False)
def _kalman(sport: str, start: date, end: date, seed: int, q: float, r: float):
    mf = _load(sport, start, end, seed)
    return mf, run_kalman(mf, q=q, r=r)


@st.cache_data(show_spinner=False)
def _strategy(sport, start, end, seed, q, r, edge_threshold, bet_fraction, juice):
    mf, trace = _kalman(sport, start, end, seed, q, r)
    return simulate_strategy(
        mf, trace,
        edge_threshold=edge_threshold,
        bet_fraction=bet_fraction,
        bookmaker_juice=juice,
        seed=seed + 1,
    )


mf = _load(sport, start, end, int(seed))
mf, trace = _kalman(sport, start, end, int(seed), q, r)

st.caption(f"data source: {getattr(mf, 'source', 'unknown')} · {len(mf.matches)} completed games")
if mf.matches.empty:
    st.warning("No completed games in this range from the live feed. Widen the date range or pick a different sport.")
    st.stop()

tab_data, tab_dist, tab_kf, tab_strat = st.tabs(
    ["Data", "Distributions", "Kalman filter", "Strategy & Sharpe"]
)

# ----------------------------- Data tab -----------------------------
with tab_data:
    c1, c2, c3 = st.columns(3)
    c1.metric("Matches", len(mf.matches))
    c2.metric("Teams", len(mf.strengths.columns))
    c3.metric("Days", (end - start).days)

    st.subheader("Match results")
    st.dataframe(
        mf.matches.assign(date=mf.matches["date"].dt.date)[
            ["date", "home", "away", "home_score", "away_score"]
        ],
        use_container_width=True,
        height=320,
    )

    st.subheader("Per-team summary")
    home_g = mf.matches.groupby("home")[["home_score", "away_score"]].agg(["mean", "count"])
    home_g.columns = ["points_for_home", "n_home", "points_against_home", "_drop"]
    away_g = mf.matches.groupby("away")[["away_score", "home_score"]].agg(["mean", "count"])
    away_g.columns = ["points_for_away", "n_away", "points_against_away", "_drop2"]
    summary = home_g.join(away_g, how="outer").drop(columns=["_drop", "_drop2"])
    summary["points_for_avg"] = summary[["points_for_home", "points_for_away"]].mean(axis=1)
    st.dataframe(summary.round(2), use_container_width=True)

# ------------------------- Distributions tab ------------------------
with tab_dist:
    st.subheader("Score distributions vs Normal")
    teams = sorted(set(mf.matches["home"]) | set(mf.matches["away"]))
    pick = st.multiselect("Teams to overlay", teams, default=teams[:3])
    if pick:
        fig = go.Figure()
        for t in pick:
            scored = pd.concat([
                mf.matches.loc[mf.matches["home"] == t, "home_score"],
                mf.matches.loc[mf.matches["away"] == t, "away_score"],
            ])
            if len(scored) < 5:
                continue
            mu, sigma = float(scored.mean()), float(scored.std())
            fig.add_trace(go.Histogram(x=scored, name=f"{t} (n={len(scored)})",
                                       opacity=0.5, histnorm="probability density"))
            xs = np.linspace(scored.min(), scored.max(), 200)
            fig.add_trace(go.Scatter(x=xs, y=stats.norm.pdf(xs, mu, sigma), mode="lines",
                                     name=f"{t} N({mu:.1f}, {sigma:.1f})"))
        fig.update_layout(barmode="overlay", height=420, xaxis_title="Score",
                          yaxis_title="Density")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("QQ plot — pooled scores vs Normal")
    pooled = pd.concat([mf.matches["home_score"], mf.matches["away_score"]])
    osm, osr = stats.probplot(pooled, dist="norm", fit=False)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=osm, y=osr, mode="markers", name="Sample"))
    line_x = np.array([osm.min(), osm.max()])
    slope, intercept = np.polyfit(osm, osr, 1)
    fig2.add_trace(go.Scatter(x=line_x, y=slope * line_x + intercept,
                              mode="lines", name="OLS fit"))
    fig2.update_layout(height=380, xaxis_title="Theoretical quantiles",
                       yaxis_title="Observed score")
    st.plotly_chart(fig2, use_container_width=True)

    sw = stats.shapiro(pooled.sample(min(len(pooled), 1000), random_state=0))
    st.caption(f"Shapiro-Wilk p={sw.pvalue:.3g} (sample of {min(len(pooled), 1000)})")

# --------------------------- Kalman tab -----------------------------
with tab_kf:
    st.subheader("Latent team strength — Kalman posterior")
    teams = list(mf.strengths.columns)
    pick = st.multiselect("Teams", teams, default=teams[:4], key="kf_teams")
    if pick:
        fig = go.Figure()
        for t in pick:
            i = teams.index(t)
            mean = trace.posterior_mean[:, i]
            sd = np.sqrt(trace.posterior_var[:, i])
            fig.add_trace(go.Scatter(x=trace.timestamps, y=mean, mode="lines", name=f"{t} mean"))
            fig.add_trace(go.Scatter(
                x=list(trace.timestamps) + list(trace.timestamps[::-1]),
                y=list(mean + sd) + list((mean - sd)[::-1]),
                fill="toself", opacity=0.15, line=dict(width=0),
                name=f"{t} ±1σ", showlegend=False,
            ))
            if not mf.strengths.empty and t in mf.strengths.columns:
                true_series = mf.strengths[t].reindex(trace.timestamps).interpolate()
                fig.add_trace(go.Scatter(x=trace.timestamps, y=true_series,
                                         mode="lines", line=dict(dash="dot"),
                                         name=f"{t} EWMA margin"))
        fig.update_layout(height=460, xaxis_title="Date", yaxis_title="Strength")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Innovation and Kalman gain")
    sub = st.selectbox("Team", teams, key="kf_one")
    i = teams.index(sub)
    inn = pd.DataFrame({"innovation": trace.innovation[:, i],
                        "gain (diag K)": trace.kalman_gain_diag[:, i]},
                       index=trace.timestamps)
    st.line_chart(inn, height=300)
    st.caption(
        "How it works — daily score margins are scaled into observations; "
        "the filter predicts forward (x ← Fx, P ← FPFᵀ + Q), then folds in the "
        "day's residual via the Kalman gain (K = PHᵀS⁻¹). Larger Q = more "
        "responsive, larger R = smoother. Full derivation in "
        "docs/derivations/kalman_filter.md."
    )

# ------------------------- Strategy tab -----------------------------
with tab_strat:
    res = _strategy(sport, start, end, int(seed), q, r, edge_threshold, bet_fraction, juice)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Sharpe (annualised)", f"{res.sharpe:.2f}")
    c2.metric("Sortino", f"{res.sortino:.2f}")
    c3.metric("Max drawdown", f"{res.max_drawdown*100:.1f}%")
    c4.metric("Win rate", f"{res.win_rate*100:.1f}%")
    c5.metric("Bets placed", res.n_bets)

    st.subheader("Equity curve")
    if not res.equity.empty:
        fig = px.line(res.equity.reset_index(), x="index", y="equity",
                      labels={"index": "date"})
        fig.update_layout(height=380)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Edge distribution (per bet)")
    if not res.bets.empty:
        fig2 = px.histogram(res.bets, x="edge", nbins=30, color="won",
                            barmode="overlay", opacity=0.65)
        fig2.update_layout(height=320)
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Bet log")
        st.dataframe(
            res.bets.assign(date=res.bets["date"].dt.date).round(4),
            use_container_width=True, height=320,
        )
    else:
        st.info("No bets cleared the edge threshold — lower it in the sidebar.")
