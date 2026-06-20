# Research Deck (frontend)

React + Vite + TypeScript dashboard for the ict-trader engine. Charts use TradingView
**Lightweight Charts** (Apache-2.0).

```bash
cd frontend
npm install
npm run dev        # http://localhost:5180, proxies /api + /ws to the FastAPI backend (:8077)
```

Start the backend first: `python scripts/run_api.py` (from the project root).

## Pages
- **Status** — engine mode, kill-switch, daily-loss usage.
- **Per-Bucket Analytics** — hit-rate + avg-R for every dimension (day, killzone, quarter,
  `daily_extreme_in`, `path_clean`, **`moved_to_be_early`**, …).
- **Equity** — cumulative R / PnL (lightweight-charts line series is the next build step).
- **Trade Journal** — every trade with its tags; flags trades where breakeven moved early.
- **Control** — kill-switch toggle (requires the control token).

## Next build steps
- **Live Monitor** tab: NQ+ES candlesticks with FVG/IFVG boxes + SMT/PSP markers + killzone
  shading, fed by the `/ws` live stream (wire to `LiveHub` broadcasts).
- Replay deep-links from the journal into the chart window.
