# CLAUDE.md — ICT Trader / Quant Research Hub

Context anchor for this project so work continues cleanly across chat sessions. Read this
first. It is the source of truth for **what this is, how it's built, and what's next**.

## What this is
A private, hosted **quant research + trader desk** for a discretionary ICT + Quarterly-Theory
intraday reversal strategy on **NQ/ES futures**. Goal: build, backtest, grade, and (eventually)
deploy strategies, capture maximum data, and quantify the documented edge leak (**moving to
breakeven on the first pullback**). The end state is a Jane-Street-style desk: log a trade →
the system auto-detects & grades every setup element (FVG, HTF delivery, SMT, PSP, killzone,
path) → it feeds a labeled dataset for model training → live executions are monitored.

Standalone project under `ict_trader/`; imports **nothing** from the surrounding sports
platform. Branch: `claude/stoic-johnson-e12crn`. Draft PR: **#2** (base is the sports branch).

## Hard constraints (do not violate)
- **Demo-only on any public host.** Live needs `ICT_TRADER_MODE=live` + `ICT_TRADER_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK`. Never set live on Render.
- **Webhook-created trades/bars are ALWAYS forced to demo.** A public URL must never write live data.
- **Never commit secrets.** Tradovate creds, dashboard password, Anthropic key live only in env (Render `sync:false` or local `.env`). The dashboard password is the user's OWN self-set value — never hardcode it.
- **Never put the assistant's model id `claude-opus-4-8`** in commits/PRs/code/artifacts — chat only. (The Claude *grading* feature may reference a different, cheaper model id like `claude-sonnet-4-6`; that's fine.)
- **Detectors are pure** (no I/O) so backtest == live. `execution/` is the only code that can lose money.
- The pre-existing sports **`test`** CI check fails on a sports-only ruff `N806` (163 errors). It is **out of scope** — the relevant check is the **`ict-trader`** workflow. Don't touch sports code; skip the `test` failure.

## Tooling / gate (run before every commit)
From `ict_trader/` with the venv active (`source .venv/bin/activate`):
- `ruff check src tests scripts` · `mypy src` (strict) · `pytest` (101+ tests).
- Frontend: `cd frontend && npm run build` (runs `tsc -b && vite build`); **commit the rebuilt `frontend/dist/`** (it's served by FastAPI and must not drift from source).

## Architecture map
```
ict_trader/
  src/ict_trader/
    config.py            # pydantic-settings; demo/live interlock; auth (require_login,
                         #   dashboard_user/password, login_password property)
    clock.py             # ET/DST + sessions/quarters/killzones
    domain/              # pure value objects: enums, bars, signals, trades
    detectors/           # 9 PURE detectors: fvg ifvg smt psp liquidity lrlr structure
                         #   quarterly timefilter  (shared live+backtest)
    confluence/          # aggregator + scoring (all-9 gate + weighted score)
    engine/              # runtime loop, bus, bootstrap (start_demo_engine = opt-in,
                         #   no-ops without Tradovate creds), pipeline
    execution/           # tradovate_rest/ws, risk, kill_switch  (only money-touching code)
    store/               # db.py, models.py (ORM), repositories.py (ONLY DB access point)
    analytics/           # metrics (summarize, equity_curve), calibration
    backtest/            # harness + sim_broker + report
    api/app.py           # FastAPI: auth/login, read endpoints (gated), control (token),
                         #   /webhooks/pine, /api/bars, serves the SPA from frontend/dist
  frontend/src/
    api.ts               # typed client; global bearer token in localStorage; 401 -> login
    App.tsx              # app shell (nav rail + topbar) + all section views
    Chart.tsx            # Lightweight Charts candlestick + long/short arrows
    theme.css            # bespoke dark "terminal" design system (no CSS framework)
  pine/                  # qict_strategy.pine (strategy, auto-webhook), qict_companion.pine
  scripts/               # run_all.py (serve), demo_seed.py (sample data), report.py
  tests/                 # unit (detectors/risk/clock) + integration/test_api.py
```

## Data model (SQLite dev → Postgres/Timescale before live; access only via repositories.py)
- `setups` — one confluence snapshot per candidate (9 booleans + score, written pass or not).
- `trades` — the analysis spine: realized R, MAE/MFE, and per-condition tags (day_of_week,
  killzone, quarter_idx, amd_phase, path_clean, **moved_to_be_early**, be_trigger,
  runner_held, exit_reason, setup_score, **mode**).
- `bars` — OHLC for charting/detection; natural key (mode,symbol,timeframe,ts) unique.
- `webhook_alerts` — raw inbound Pine alerts. `orders`, `equity` also present.
- Planned: `trade_analysis` (detected elements jsonb + deterministic score + Claude grade).

## Webhook contract (`POST /webhooks/pine`) — the demo data path (no broker API)
Optional shared secret = `ICT_TRADER_WEBHOOK_SECRET`. `kind` selects behavior:
- `kind:"signal"` — a setup notification (logged, shows in Signals).
- `kind:"trade"` — a closed round-trip → logged as a **demo** Trade (feeds analytics). Fields:
  side, entry, exit, realized_r, killzone, quarter, day_of_week, moved_to_be_early,
  path_clean, exit_reason.
- `bars:[...]` + `timeframe`,`symbol` — OHLC bars (compact `t/o/h/l/c/v` or full names; unix
  or ISO ts) → stored under demo for charts. Idempotent on re-send.

## Env vars
Auth: `ICT_TRADER_REQUIRE_LOGIN` (true on Render), `ICT_TRADER_DASHBOARD_USER`,
`ICT_TRADER_DASHBOARD_PASSWORD` (falls back to control token). `ICT_TRADER_CONTROL_TOKEN`
(auto-gen on Render) gates control actions. `ICT_TRADER_WEBHOOK_SECRET`. `ICT_TRADER_MODE`
(demo). `ICT_TRADER_ENGINE_AUTOSTART` (false; needs Tradovate API creds, unavailable on demo).
Planned: `ANTHROPIC_API_KEY` for the Claude trade-grader (no-ops if unset). `TRADOVATE_*` are
**optional** and stay blank on demo.

## Deploy
`render.yaml` blueprint → one Docker web service serving UI+API. Demo-only, login required.
See `DEPLOY.md`. Live URL: ict-trader-deck.onrender.com (blueprint has `autoDeploy:false` →
user clicks Manual Deploy). Local: `python scripts/run_all.py` or `run-deck-mac.command`.

## Roadmap & status
- **A — UI foundation** ✅ shipped. Quant-desk shell (nav rail + topbar), theme.css design
  system, Overview/stat tiles, restyled all views, login screen. Section IA in place.
- **B — Charts + webhook bars** ✅ shipped (deck). bars table + webhook v2 + `/api/bars` +
  Lightweight Charts candles with long/short arrows + sample-bar seed.
  - **B remainder (next):** emit a **bar-feed alert** from `pine/qict_strategy.pine` (latest
    closed bar as JSON) + document it in `TRADINGVIEW.md`, so live candles flow (today only
    seeded demo bars render). Also: FVG/IFVG boxes + killzone shading overlays on the chart.
- **D — Auto-detection** ✅ shipped. `analytics/trade_analyzer.py` runs the FVG / IFVG / LTF
  trigger / market-structure detectors over a logged trade's bar window + the trade's
  timing/path tags → 6 weighted elements, a 0..1 deterministic score and A–D grade, stored in
  `trade_analysis`. Auto-runs when any trade is logged (webhook or /api/trades); surfaced via
  `GET /api/trades/{id}/analysis`, in `/api/trades` (grade column), and expandable in the
  Journal. Seed grades the demo trades.
- **C — Click-to-log tool**: click a chart point → choose entry → `POST /api/log-entry`
  creates a demo trade; trade↔chart linkage; the entry feeds the dataset.
- **E — Claude grading** ✅ shipped. `llm/grader.py` (lazy `anthropic` SDK, cost-efficient model
  via `ICT_TRADER_GRADER_MODEL`) grades each logged trade's SETUP quality (A–F + ≤2-sentence
  rationale, penalizing breakeven-early). Optional + no-op without `ANTHROPIC_API_KEY`; runs
  off-thread on log; stored in `trade_analysis.llm_grade/llm_rationale`; shown in the Journal
  expand. `anthropic` is the optional `[llm]` extra (not in CI). render.yaml has `ANTHROPIC_API_KEY`
  (sync:false).
- **F — Dataset** ✅ shipped. `/api/dataset` (preview) + `/api/dataset/export?format=jsonl|csv`
  flatten every trade to a labeled feature row (tags + detected-element booleans + outcome
  `realized_r`/`win`); Dataset section previews the table and downloads JSONL/CSV.
- **G — Strategies + live-exec monitor**: strategy config CRUD; pipeline-step status
  (feed→detectors→aggregator→risk→execution) over the WS hub, shown live.
- **Final**: keep this CLAUDE.md current; arm the improvement `/loop`.

## Decisions locked with the user
- Bars arrive via the **TradingView webhook** (no DataBento/Tradovate API on demo).
- Trade grading = **detectors (deterministic tags) + a Claude API narrative grade**.
- Charts = **Lightweight Charts** (free, embeddable; supports our arrows + click-to-mark).
- UI styling = bespoke dark theme via `theme.css` (zero build deps), not Tailwind/Mantine.

## Useful tooling (MCP servers & skills)
**MCP servers — already available in Claude Code on the web (no install needed):**
- **GitHub** (`mcp__github__*`) — PRs, CI logs, reviews; used to manage PR #2.
- **Bigdata.com** (`mcp__Bigdata_com__*`) — financial/market data, company & market tearsheets,
  news sentiment, events calendar. Useful for macro/news context around NQ/ES sessions and the
  8:30 ET news-block filter research.
- Others are available but off-topic (Notion, Gmail, Google Drive, Zoom). External
  market-data/broker MCP servers can't be auto-installed here (they need credentials/config);
  add them in Claude Code settings if/when API access exists.

**Skills useful for this project:**
- `/code-review`, `/simplify` — review/clean the diff before pushing.
- `/verify`, `/run` — drive the deck to confirm a change works in the real app.
- `claude-api` — consult when building the **Phase E** Claude trade-grader (model ids/params).
- `deep-research` — multi-source research (validating ICT concepts, data-feed options).
- `session-start-hook`, `update-config` — set up an env-bootstrap hook / settings (persistent
  `.claude/` change; needs the user's explicit approval).

**Env-bootstrap hook (optional, needs approval):** a `.claude/hooks/session-start.sh` that
auto-installs the venv (`.[serve,dev]`) + frontend deps so web sessions can run the gate
instantly. The script is ready (venv create + `pip install -e ".[serve,dev]"` + `npm install`),
but the safety system blocks adding auto-run hooks unless the user explicitly asks for it.

## How to continue in a new chat
1. `cd ict_trader && source .venv/bin/activate`; confirm the gate is green.
2. Pick the next roadmap item (start with **B remainder**, then C). Keep detectors pure.
3. Add tests, run the gate, rebuild `frontend/dist`, commit, push to
   `claude/stoic-johnson-e12crn`, keep PR #2 updated. Update this file's status.
