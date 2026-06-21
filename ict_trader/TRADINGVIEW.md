# Demo-trading on TradingView (no Tradovate API, demo-only)

**Why this is the path for you:** Tradovate's REST/WS API needs a *funded live* account
(the ~$1k minimum / API Access add-on). On a pure demo you can't get API creds, so Python
can't drive Tradovate directly. The one **official** way to get data out of TradingView is a
**webhook alert**. So TradingView is the front-end + data source, webhooks carry the data to
the research deck, and the deck does the analytics. No broker API anywhere.

There are two ways to use it. Most people want **B** (it captures data automatically).

- **A — Indicator + manual journaling.** The `qict_companion.pine` *indicator* marks setups
  and alerts you; you click-trade on TradingView Paper Trading (or Tradovate demo inside TV)
  and log each fill in the deck's **Log Trade** tab. Faithful to *your* discretionary fills.
- **B — Strategy + automatic webhook capture.** The `qict_strategy.pine` *strategy* encodes
  the executable rules, backtests in TradingView's Strategy Tester, and on every closed trade
  POSTs a JSON webhook to the deck — which logs it as a demo trade automatically. **No manual
  journaling.** This is the "all the info is extracted" path.

> Honesty: both Pine files are a **simplified** approximation of the engine (no nested SMT,
> no true low-resistance-path scan). The Python engine in this repo is the faithful detector.
> Also: **TradingView webhooks require a paid TV plan** (Essential/Plus/Premium). Your
> futures-data subscription should cover it; the free tier won't POST.

---

## Prerequisite: a public deck URL

Webhooks need somewhere to POST. Deploy the deck once (see `DEPLOY.md`) to get a URL like
`https://ict-trader-deck.onrender.com`. You do **not** need any Tradovate creds for this —
leave those env fields blank. Note the auto-generated **`ICT_TRADER_WEBHOOK_SECRET`** from the
Render dashboard (Environment tab); you'll paste it into the Pine input.

---

## Path B — Strategy + automatic webhook capture (recommended)

1. **Log in & open the chart.** tradingview.com → sign in (Google SSO) → open
   **`CME_MINI:NQ1!`**, timeframe **5m** (1m/3m for finer entries).
2. **Add the strategy.** Bottom panel → **Pine Editor** → paste all of
   `ict_trader/pine/qict_strategy.pine` → **Add to chart**.
3. **Configure inputs (gear):**
   - **Correlated symbol (ES)** → `CME_MINI:ES1!`.
   - **Webhook shared secret** → paste your `ICT_TRADER_WEBHOOK_SECRET`.
   - **Move to breakeven early?** → leave **OFF** to trade the model correctly (hold the
     runner). Flip it ON later to measure the leak — see the experiment below.
4. **Backtest for free first.** Open the **Strategy Tester** tab (bottom). You instantly get
   net profit, win rate, profit factor, and the trade list across all loaded history — no
   webhook needed yet. This alone validates the rules on your data.
5. **Send fills to the deck.** Right-click chart → **Add alert** →
   - Condition: **ICT Quarterly STRATEGY**.
   - Trigger the alert on **"alert() function calls only"** (so each closed trade fires once).
   - **Webhook URL** (under Notifications): `https://<your-deck>.onrender.com/webhooks/pine`.
   - Leave the message as `{{strategy.order.alert_message}}` *or* blank — the strategy builds
     its own JSON (with your secret) in the `alert()` call.
   Click **Create.** Now every closed trade lands in the deck under the **demo** selector and
   shows in the **Signals**, **Trade Journal**, **Per-Bucket** and **Equity** tabs.

### The headline experiment (quantify your documented leak)
Run the Strategy Tester with **Move to breakeven early? OFF**, note net profit / avg trade.
Flip it **ON** and compare. The difference is the cost of moving to breakeven on the first
pullback — the exact flaw this project exists to measure. In the deck, the **Per-Bucket
Analytics → moved_to_be_early** rows show the same split in R, accumulated from the webhook.

---

## Path A — Indicator + manual journaling

1. Add `ict_trader/pine/qict_companion.pine` as above (it's an **indicator**, not a strategy).
2. Trading Panel → **Paper Trading** → **Connect** (or connect your **Tradovate demo** inside
   TradingView and click-trade there).
3. Add an alert: Condition **ICT Quarterly Companion** → **ICT Long/Short**, **Once Per Bar
   Close**. The readable message gives **entry / stop / target**.
4. When a BUY/SELL prints in the NY-AM killzone (not Friday / not 8:30 news): enter near the
   inverse-FVG level, stop just beyond it, scale out at interim liquidity, and **hold a runner
   to the PDH/PDL (ERL) line**. **Do NOT move to breakeven on the first pullback** — only after
   price breaks structure in your favour.
5. **Log each trade** in the deck's **Log Trade** tab (paste the control token,
   `ICT_TRADER_CONTROL_TOKEN`), being honest about the **moved-to-BE-early** checkbox. Switch
   the **data** selector to **demo** and watch Per-Bucket Analytics build.

---

## Notes / troubleshooting
- **Nothing arrives in the deck?** Confirm the alert's Webhook URL is exactly
  `…/webhooks/pine`, the secret matches `ICT_TRADER_WEBHOOK_SECRET`, and your TV plan supports
  webhooks. Check the **Signals** tab — even rejected-secret posts won't show, but accepted
  signal alerts will.
- **No BUY/SELL ever prints?** The composite needs killzone + IFVG + SMT + PSP together; it's
  intentionally rare. Watch the component marks and use discretion.
- **Pine compile error on paste?** Send me the exact error text — I'll fix the script.
- **Security:** the webhook only ever writes **demo** trades; a public URL can never inject
  live-mode data, and control actions still need the control token.
