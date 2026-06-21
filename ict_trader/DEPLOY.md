# Deploy the deck to a free cloud URL (Render)

Get a real, clickable `https://…` link you can open from your phone or any computer — no
local setup. **DEMO only.** Free tier; the service sleeps when idle (first open after a nap
takes ~30–60s) and its data is ephemeral (sample data reseeds on each boot).

## One-click

1. Push this branch to your GitHub (already done) and sign in to <https://render.com> with
   **GitHub** (free).
2. Open this deploy link (it reads `render.yaml` from the repo):

   **https://render.com/deploy?repo=https://github.com/essam2007/predictormaster/tree/claude/stoic-johnson-e12crn**

3. Render shows the blueprint (one web service, Docker). Click **Apply / Create**. First
   build takes a few minutes (it builds the UI + API).
4. When it's live, Render gives you a URL like **`https://ict-trader-deck.onrender.com`** —
   that's your clickable deck. It opens to a **login screen** (see below); sign in and the
   analytics tabs are pre-seeded.

## Your private login (single-user cockpit)

The blueprint ships `ICT_TRADER_REQUIRE_LOGIN=true`, so the public URL shows a **sign-in
screen** first — only you get in. Set your own credentials in Render → Environment:

- **`ICT_TRADER_DASHBOARD_USER`** — your username (defaults to `admin` if left blank).
- **`ICT_TRADER_DASHBOARD_PASSWORD`** — **your own** password. If you leave it blank it
  falls back to the auto-generated `ICT_TRADER_CONTROL_TOKEN` (find it under Environment).

Signing in stores a token in your browser and also authorizes the control actions (kill
switch, broker test, Log-Trade), so you never paste a token by hand. These are your
details on your own deck — nothing is sent anywhere else. To run the deck **open** (e.g.
locally), set `ICT_TRADER_REQUIRE_LOGIN=false`.

## Demo-only? Leave the Tradovate fields blank.

Tradovate's API needs a **funded live** account (the ~$1k minimum / API Access add-on), so a
pure demo can't connect Python to Tradovate. **That's fine** — on a demo you feed the deck
through the **TradingView webhook** instead (next section). Leave all `TRADOVATE_*` env fields
empty; the blueprint pins `ICT_TRADER_ENGINE_AUTOSTART=false` and the deck runs perfectly
without them.

*(If you ever DO get Tradovate API creds, set `TRADOVATE_NAME / PASSWORD / CID / SECRET` in
Environment and flip `ICT_TRADER_ENGINE_AUTOSTART=true` — the deck will then auto-stream your
demo data and paper-trade in-process, and Status shows `engine_running: true`.)*

## Connect TradingView (webhook) — the demo data path

This is how your trades reach the deck with **no broker API**:

1. Note the auto-generated **`ICT_TRADER_WEBHOOK_SECRET`** in Render → Environment.
2. In TradingView, run `ict_trader/pine/qict_strategy.pine` (the **strategy** — auto-captures
   fills) or `qict_companion.pine` (indicator — you journal manually). Paste the secret into
   its **Webhook shared secret** input.
3. Add a TradingView **alert** → trigger **"alert() function calls only"** (strategy) or
   **Once Per Bar Close** (indicator) → **Webhook URL**:
   `https://<your-deck>.onrender.com/webhooks/pine`
4. Each closed strategy trade now lands in the deck as a **demo** trade — visible under the
   **Signals**, **Trade Journal**, **Per-Bucket** and **Equity** tabs. Full step-by-step:
   `ict_trader/TRADINGVIEW.md`.

## Safety
- The blueprint pins `ICT_TRADER_MODE=demo`. **Never** set it to `live` on a public host.
- Control actions (kill switch, backtest, trade logging, broker test) require the
  auto-generated control token, so the public URL can't trigger them without it.
- Free tier has no persistent disk, so logged trades reset on redeploy. For durable history,
  attach a Render Postgres instance and set `ICT_TRADER_DB_URL=postgresql+asyncpg://…`.

## Other hosts
The same `ict_trader/Dockerfile` runs on Fly.io, Railway, Koyeb, etc. — point them at it and
set `ICT_TRADER_API_HOST=0.0.0.0`; the app already honors the platform's `$PORT`.
