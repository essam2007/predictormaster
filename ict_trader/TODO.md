# TODO / Backlog — ICT Trader

Single source of truth for what's planned but not yet built. Shipped phases live in `CLAUDE.md`.

## ⭐ Priority — Setup Review & Rating Queue (training accelerator)
**Why:** labeling setups by hand (one markdown file each) is slow. A queue that *surfaces*
candidate setups and lets the trader *rate them in seconds* will build the labeled corpus —
and teach the grading model — far faster. This is the engine of the Training-Plan loop.

**What it does:**
1. **Scan** OHLC (this week's `data/*.csv`, or a backtest date range, or live webhook bars) with
   the detector suite → auto-surface candidate reversal setups (FVG + IFVG + SMT + PSP + killzone
   confluence), each with an auto-grade (A+→D) from the rubric.
2. **Present** each candidate one at a time: annotated candlestick chart (FVG boxes, SSMT/PSP
   marks, entry/stop/target) + the auto-grade + which pillars fired/missing.
3. **Rate in one click:** agree / override the grade, take / pass, optional one-line note.
   Keyboard-fast (e.g. `1–5` for grade, `t/p` for take/pass, Enter = next).
4. **Store** each rating as a labeled training row (rubric tags + trader verdict) → feeds the
   deck dataset (`/api/dataset`) and the calibration step (tune detector weights until
   auto-grade ≈ trader grade).

**Acceptance:** from a week of data, the trader can review + rate ~20–50 surfaced setups in a few
minutes, and the labeled rows export to JSONL/CSV for model training.

**Build sketch:**
- `analytics/setup_scanner.py` — slide the detectors over co-bars, emit ranked candidate setups
  (reuse `trade_analyzer` + the backtest harness).
- `POST /api/setups/scan` (range/mode) → candidates; `POST /api/setups/{id}/rate` → labeled row.
- Frontend **Review** tab: card-at-a-time, annotated chart, keyboard rating.
- Depends on the chart-image/overlay annotator (below).

## Other open items
- **Chart-image / overlay annotator** — render any setup's bars to an annotated PNG (FVG/IFVG
  boxes, killzone shading, SSMT/PSP marks, entry/stop/target). Needed by the Review queue and the
  "photos of the setup" request. Demo on `data/*.csv` first.
- **Phase G** — strategy config management + live pipeline-step monitor (feed→detectors→
  aggregator→risk→execution).
- **Rubric calibration** — once the trader answers the 5 open questions in
  `journal/Strategy/Grading-Rubric.md`, tune the aggregator weights so auto-grade == their grade.
- **Deeper data feed** — Yahoo intraday is ~5 trading days; for real history evaluate DataBento /
  a TradingView export so the scanner has months of setups to surface.
- **Real two-stage SMT / nested LRLR** in the detectors (current detectors are simplified).
