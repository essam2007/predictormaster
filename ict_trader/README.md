# ict-trader

Standalone algorithmic execution + research platform for an **ICT + Quarterly-Theory
intraday reversal** strategy on NQ/ES E-mini futures.

> This project is intentionally isolated from the surrounding `predictormaster`
> (sports-forecasting) repository — it has its own `pyproject.toml`, package, and deps,
> and imports nothing from it.

## What it does

Python is the brain. One asyncio engine ingests time-aligned **ES + NQ** bars, runs one
**detector per ICT component**, an **aggregator** turns those component states into an
entry intent, and an **execution/risk engine** places bracketed orders on **Tradovate**
(demo endpoint first, live later). Everything is logged so a **research deck** can compute
per-condition hit-rate and average R — the whole point being to *validate the strategy on
your own fills* and quantify the documented "breakeven-too-early" leak.

TradingView is used for **visualization + phone management**: a Pine v6 companion mirrors
the Python detections, and orders placed via the API appear in TradingView's native
Tradovate broker panel.

### The strategy stack (the "A+" setup)

1. HTF (15m/1h) unfilled FVG in the bias direction, in discount (longs) / premium (shorts)
2. Stage-1 ES/NQ SMT divergence at a liquidity level
3. Stage-2 nested SMT (same direction)
4. PSP — candle-level opposing closes between ES and NQ
5. LTF FVG + Inverse-FVG trigger (body-close polarity flip)
6. Clean low-resistance path to the day's high/low (external range liquidity)
7. NY-AM killzone / macro / Silver-Bullet timing, daily extreme not yet in
8. Day filter (prefer Tue/Wed, avoid Fri + high-impact news)
9. Management: partials + a **runner to ERL**, trail behind structure, **no early breakeven**

## Layout

```
src/ict_trader/
  clock.py          ET/DST sessions + 90-minute quarters (single source of time)
  config.py         demo/live settings loader
  domain/           pure value objects (bars, pd-arrays, signals, trades)
  detectors/        one pure detector per ICT component (shared live + backtest)
  confluence/       aggregator + scoring (all-9 gate + weighted score)
  marketdata/       MarketFeed protocol, bar builder, ES/NQ sync, replay
  engine/           asyncio runtime + event bus + rolling state
  execution/        Tradovate client, order router, position manager, risk, kill switch
  store/            SQLAlchemy models + repositories (SQLite -> Postgres/Timescale)
  backtest/         replay harness + simulated broker + CLI
  analytics/        per-bucket metrics + component calibration
  api/              FastAPI research-deck backend + Pine webhook receiver
pine/               Pine v6 companion indicator
frontend/           React + Vite research deck (scaffold)
```

The `detectors/` are **pure functions of bar state** (no I/O, no broker) so the backtester
runs the *identical* code path as live. The `execution/` package is the only thing that
talks to the broker and holds every risk interlock.

## Install & test

```bash
cd ict_trader
uv venv && source .venv/bin/activate           # or: python -m venv .venv
uv pip install -e ".[dev]"                      # pure core + test tooling
uv pip install -e ".[dev,serve]"                # + async engine / API / DB
pytest                                          # unit + e2e (no network)
ruff check . && mypy
```

## Run the research deck (one command)

```bash
cd ict_trader
pip install -e ".[serve]"
python scripts/run_all.py        # builds the UI (first run), seeds sample data, serves both
# open the printed URL (default http://127.0.0.1:8077) — UI + API on one port
```

> The **interactive deck is a web server** — view it by running this on **your own
> computer** and opening the URL. Isolated/headless environments (e.g. the Claude web
> container) can't expose the port, so use the static report instead:

```bash
python scripts/report.py --mode demo --out report.html   # self-contained HTML, no server
```

`report.py` renders the same analytics (overall, per-bucket hit-rate/avg-R incl. the
breakeven-leak, equity curve, journal, calibration) as a single openable file from your
trades.

`run_all.py` builds the React deck if needed, seeds illustrative sample trades when the
store is empty (so the analytics tabs aren't blank), and serves the SPA + JSON API from a
single port. Use `--no-seed` / `--no-build` to skip those.

To connect your Tradovate account (demo first): put `TRADOVATE_*` in `.env`, then
`python scripts/test_tradovate.py` (or the **Test Tradovate connection** button on the
deck's Control tab — set `ICT_TRADER_CONTROL_TOKEN` first).

## Backtest

```bash
ict-backtest --csv-es data/es_1m.csv --csv-nq data/nq_1m.csv
# writes setups/trades into the store; inspect via the analytics module / research deck
```

## Safety

- **Demo first.** The live Tradovate endpoint requires both `ICT_TRADER_MODE=live` and an
  explicit confirmation env var; default size is reduced and a daily-loss limit + kill
  switch are enforced.
- Detectors fire on **closed bars only** (repaint-safe). SMT/PSP refuse to fire on
  unsynced ES/NQ co-bars.
- There is **no validated edge** for this strategy — treat early live trading as continued
  data collection. See `/root/.claude/plans/read-this-research-toasty-dragonfly.md`.
