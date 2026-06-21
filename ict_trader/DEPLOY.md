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
   that's your clickable deck. Open it: the analytics tabs are pre-seeded.

## Connect your Tradovate (demo) account

In the Render dashboard → your service → **Environment**, set these (they were created as
"sync:false" so they're never in git):

```
TRADOVATE_NAME      your Tradovate login
TRADOVATE_PASSWORD  your password
TRADOVATE_CID       from your Tradovate API app
TRADOVATE_SECRET    from your Tradovate API app
TRADOVATE_ES_SYMBOL ESM5   (current front-month, optional)
TRADOVATE_NQ_SYMBOL NQM5
```

Save → Render redeploys. The blueprint sets `ICT_TRADER_ENGINE_AUTOSTART=true`, so once your
creds are present the hosted deck **automatically connects to your Tradovate DEMO account,
streams ES/NQ data, and paper-trades** the strategy — its setups/trades show up under the
**demo** data selector, and **Status** shows `engine_running: true`. To verify the link
manually: on the **Control** tab paste the **control token** (find it under Environment as
`ICT_TRADER_CONTROL_TOKEN`) and click **Test Tradovate connection**. It stays PAPER (no real
orders) on the public host.

## Connect your TradingView demo (webhook)

Your TradingView Paper-Trading signals can flow into the same hosted deck:

1. In TradingView, add an alert on the **ICT Quarterly Companion** indicator (Once Per Bar
   Close). Set the alert's **Webhook URL** to:
   `https://<your-deck>.onrender.com/webhooks/pine`
2. Make the alert message JSON include your webhook secret, e.g.
   `{"source":"pine","secret":"<ICT_TRADER_WEBHOOK_SECRET from Render>","symbol":"NQ","bias":"long"}`
   (the indicator's built-in webhook message already has this shape — paste your secret into
   its "Webhook shared secret" input).
3. Alerts now land in the deck (logged + pushed live), so your TradingView demo and the
   Tradovate demo engine feed the same analytics.

## Safety
- The blueprint pins `ICT_TRADER_MODE=demo`. **Never** set it to `live` on a public host.
- Control actions (kill switch, backtest, trade logging, broker test) require the
  auto-generated control token, so the public URL can't trigger them without it.
- Free tier has no persistent disk, so logged trades reset on redeploy. For durable history,
  attach a Render Postgres instance and set `ICT_TRADER_DB_URL=postgresql+asyncpg://…`.

## Other hosts
The same `ict_trader/Dockerfile` runs on Fly.io, Railway, Koyeb, etc. — point them at it and
set `ICT_TRADER_API_HOST=0.0.0.0`; the app already honors the platform's `$PORT`.
