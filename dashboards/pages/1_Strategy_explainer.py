"""Plain-English explanation of the current strategy + a sensitivity table
that backs the explanation with real numbers.

Streamlit multi-page convention: any file in dashboards/pages/ becomes a
sidebar nav entry. The numeric prefix orders the entries.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboards._data import (  # noqa: E402
    SPORTS,
    generate_matches,
    run_kalman,
    simulate_strategy,
)

st.set_page_config(page_title="Strategy explainer", layout="wide")
st.title("Strategy explained — in plain English")

st.markdown(
    """
This page describes exactly what the betting strategy on the **Strategy
& Sharpe** tab does, then re-runs it across five different *minimum-edge*
settings on real game data so you can see how the choice changes the
results.

---

### What the strategy does, in five steps

1. **Pull every completed game** in the chosen sport and date window from
   the public source (ESPN, MLB Stats API, NHL public schedule, or
   football-data.co.uk). No synthetic data.
2. **Track each team's strength over time** with a Kalman filter on the
   daily score margin. The filter's posterior mean is the model's best
   estimate of how good a team is *as of the morning of each match*.
3. **Turn the strength gap into a win probability.** When the home team
   has a higher posterior strength, the model assigns it a higher
   probability of winning that match.
4. **Compare to the actual closing odds.** We de-vig the bookmaker's two
   prices (so they sum to 100%) and compute the **edge** —
   *model probability − market probability*.
5. **Bet only when the edge is large enough.** If `edge ≥ threshold`, place
   a flat-fraction stake at the actual closing odds. Settle the bet using
   the real game outcome. No bet, no synthetic price.

> **Nothing in the calculation is invented.** Win/loss comes from the box
> score, odds come from the bookmaker, and equity is the cumulative
> settled P&L. Sharpe, drawdown, and CLV are computed from that bankroll
> series.
"""
)

with st.sidebar:
    st.header("Scenario")
    sport = st.selectbox("Sport", SPORTS, index=SPORTS.index("epl") if "epl" in SPORTS else 0)
    today = date.today()
    default_start = today - timedelta(days=270)
    start = st.date_input("Start date", default_start, max_value=today - timedelta(days=14))
    end = st.date_input("End date", today, min_value=start + timedelta(days=14))
    st.header("Fixed knobs")
    q = st.slider("Kalman Q (process noise)", 0.001, 0.5, 0.02, step=0.001, format="%.3f")
    r = st.slider("Kalman R (observation noise)", 0.05, 5.0, 0.5, step=0.05)
    bet_fraction = st.slider("Stake (fraction of bankroll)", 0.001, 0.10, 0.02, step=0.001, format="%.3f")


@st.cache_data(show_spinner="loading real games…")
def _load(sport, start, end):
    return generate_matches(sport, start, end)


@st.cache_data(show_spinner="running Kalman filter…")
def _kalman(sport, start, end, q, r):
    mf = _load(sport, start, end)
    return mf, run_kalman(mf, q=q, r=r)


try:
    mf, trace = _kalman(sport, start, end, q, r)
except Exception as e:
    st.error("Failed to load data for this scenario.")
    st.exception(e)
    st.stop()

st.caption(f"data source: {getattr(mf, 'source', 'unknown')} · {len(mf.matches)} completed games · {start} → {end}")

if mf.matches.empty:
    st.warning("No completed games in that window. Widen the range or pick a different sport.")
    st.stop()

# ----------------- Sensitivity table -----------------
st.subheader("Results across five minimum-edge thresholds")
st.markdown(
    "Same data, same Kalman filter, same stake size — only the **minimum edge "
    "to bet** changes between rows. A higher threshold means we bet less often "
    "but only on the spots the model is most confident about."
)

THRESHOLDS = [0.01, 0.03, 0.05, 0.07, 0.10]
records = []
for th in THRESHOLDS:
    res = simulate_strategy(mf, trace, edge_threshold=th, bet_fraction=bet_fraction)
    final_bankroll = float(res.equity.iloc[-1]) if len(res.equity) else 1.0
    records.append({
        "min edge": f"{th*100:.0f}%",
        "bets placed": int(res.n_bets),
        "win rate": f"{res.win_rate*100:.1f}%" if res.n_bets else "—",
        "Sharpe (annualised)": round(res.sharpe, 2) if res.n_bets else None,
        "max drawdown": f"{res.max_drawdown*100:.1f}%" if res.n_bets else "—",
        "closing line value": round(res.closing_line_value, 4) if res.n_bets else None,
        "ending bankroll (start = 1.00)": round(final_bankroll, 3),
    })

df = pd.DataFrame.from_records(records)
st.dataframe(df, use_container_width=True, hide_index=True)

# Auto-generated takeaway based on the table.
non_empty = [r for r in records if r["bets placed"] > 0]
if non_empty:
    best = max(non_empty, key=lambda r: r["Sharpe (annualised)"] or float("-inf"))
    worst = min(non_empty, key=lambda r: r["Sharpe (annualised)"] or float("inf"))
    st.markdown(
        f"**What this table is telling you for {sport.upper()} {start} → {end}:** "
        f"the best Sharpe came at a **{best['min edge']} minimum edge** "
        f"({best['bets placed']} bets, ending bankroll {best['ending bankroll (start = 1.00)']:.2f}), "
        f"the worst at **{worst['min edge']}** "
        f"({worst['bets placed']} bets, ending bankroll {worst['ending bankroll (start = 1.00)']:.2f}). "
        "Negative Sharpe means the strategy lost money on a risk-adjusted basis at that threshold."
    )
else:
    st.info(
        "No bets cleared any threshold for this scenario — usually because the "
        "free data feed for the picked sport doesn't carry odds (MLB and NHL "
        "via the public APIs). EPL and NBA give the cleanest sensitivity tables."
    )

# ----------------- Glossary -----------------
st.subheader("How to read the columns")
glossary = pd.DataFrame.from_records([
    {"term": "min edge",
     "meaning": "How much the model's win probability has to exceed the market's before we bet. 3% is a common starting point."},
    {"term": "bets placed",
     "meaning": "Total number of games where the model's edge cleared the threshold AND odds were available."},
    {"term": "win rate",
     "meaning": "Of the bets we placed, what fraction won. At fair odds, break-even is roughly 1 / (1 + decimal_odds − 1)."},
    {"term": "Sharpe (annualised)",
     "meaning": "Daily P&L mean divided by daily P&L stdev, scaled by √252. Above 1 is good; above 2 is institutional."},
    {"term": "max drawdown",
     "meaning": "Worst peak-to-trough decline of the equity curve. −20% means the bankroll lost a fifth from a previous high before recovering."},
    {"term": "closing line value",
     "meaning": "Average gap between our model probability and the market's de-vigged probability on bets we took. Positive CLV is the strongest leading indicator of a profitable strategy."},
    {"term": "ending bankroll",
     "meaning": "Where 1 unit of starting capital ended up after the entire window. 1.10 = +10%, 0.85 = −15%."},
])
st.dataframe(glossary, use_container_width=True, hide_index=True)

st.markdown(
    """
---
### How to use this page
- Start with **EPL** if you want a clean test — it ships with full closing
  odds for every match in the season, so every bet settles at a real
  bookmaker price.
- Try **NBA** for a much larger sample, but expect fewer bets to settle
  because ESPN doesn't publish a closing line on every game.
- If every row shows zero bets, the chosen sport's free feed has no odds.
  Add `THE_ODDS_API_KEY` to your environment to widen coverage (see
  `docs/data_sources.md`).
- The **Strategy & Sharpe** tab on the main page lets you pick *one* edge
  threshold and inspect the bet-by-bet log; this page sweeps that knob so
  you can see the trade-off at a glance.
"""
)
