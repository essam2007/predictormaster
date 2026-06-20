# Demo-trading on TradingView Paper Trading (no API keys)

The fastest way to start: trade TradingView's **built-in Paper Trading** account by hand,
using our indicator for signals, and log each trade into the research deck so the analytics
still build up. No Tradovate API, no add-on.

> You do the login and the clicks (only you can — never share your Google password). The
> indicator is a **simplified visual aid**; the Python engine in this repo is the faithful
> detector.

## 1. Log in & open the chart
1. Go to **tradingview.com** and sign in (the **Google** button does Google SSO).
2. Open a chart for **`CME_MINI:NQ1!`** (NQ front-month). Set the timeframe to **5m** (use
   1m/3m for finer entries).

## 2. Add the indicator
1. Bottom panel → **Pine Editor**.
2. Open `ict_trader/pine/qict_companion.pine` from this repo, copy all of it, paste it into
   the editor (replace the template).
3. Click **Add to chart**.
4. Open the indicator's **settings (gear)** → set **Correlated symbol (ES)** to the matching
   ES contract (e.g. `CME_MINI:ES1!`). Toggle what you want to see.

You'll now see: FVG boxes, inverse-FVG (entry) boxes, ES/NQ **SMT** triangles, **PSP** dots,
killzone/Silver-Bullet shading, dashed **PDH/PDL** target lines, and **BUY/SELL** labels when
a setup lines up.

## 3. Turn on Paper Trading
1. Bottom panel → **Trading Panel** → choose **Paper Trading** → **Connect**.
2. (Optional) TradingView paper accounts start with virtual cash; reset/resize in the panel.

## 4. Get alerted when a setup prints
1. Right-click the chart → **Add alert** (or the alarm icon).
2. Condition: **ICT Quarterly Companion** → **ICT Long** (or **ICT Short**), or alert on the
   **BUY/SELL** marker.
3. Trigger: **Once Per Bar Close** (avoids repaint). Add the Slack/phone/email notification
   you want. The readable alert tells you the **entry / stop / target**.

## 5. Place & manage the paper trade
When a **BUY**/**SELL** prints in the NY-AM killzone (and it's not Friday / 8:30 news):
- Enter near the **inverse-FVG** level; stop just beyond it (the alert gives both).
- **Targets:** scale out at interim liquidity, **hold a runner for the PDH/PDL (ERL) line.**
- **The one rule that matters:** do **NOT** move your stop to breakeven on the first
  pullback — only after price breaks structure in your favour. That single habit is the
  documented edge-killer this whole project exists to fix.

## 6. Log it so the deck learns
Run the deck (`python scripts/run_all.py`, see README), open it, go to the **Log Trade** tab,
paste your control token (`ICT_TRADER_CONTROL_TOKEN` from `.env`), and record the trade —
especially the **"moved to BE early"** checkbox. Then switch the top **data** selector to
**demo** and watch **Per-Bucket Analytics**: after ~20–30 trades the `be_early` vs
`no_be_early` rows will show you, in your own R, what the early-breakeven habit costs.

## Notes / troubleshooting
- **No BUY/SELL ever prints?** The composite needs killzone + IFVG + SMT together; it's
  intentionally rare. Watch the individual marks (SMT/PSP/FVG) and use discretion.
- **Pine compile error on paste?** Send me the exact error text — I'll fix the script.
- This is **manual** trading; TradingView cannot auto-fire a Pine strategy to a broker. For
  automation, use the Python engine path (`scripts/run_engine.py`) instead.
