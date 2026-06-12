"""Operations dashboard — local web UI to monitor and control the bot.

Runs at http://127.0.0.1:8765 by default. Trusts whoever can reach
that loopback address; do NOT bind to a public interface without
adding auth.

What's here:
  - app.py: FastAPI app, /api endpoints + static HTML/JS frontend
  - runner.py: subprocess manager for scripts/live_runner.py
  - metrics.py: PnL / Sharpe / win-rate from logs/decisions.jsonl
  - balance.py: USDC proxy + MATIC EOA balances via Polygon RPC
"""
