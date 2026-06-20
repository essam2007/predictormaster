#!/bin/bash
# Double-click this file in Finder to start the ICT Trader research deck on your Mac.
# First run: macOS may say "unidentified developer" — right-click the file -> Open -> Open.
#
# Requires Python 3 (install from https://www.python.org/downloads/ if you don't have it).
# It creates a local virtual environment, installs the app, opens your browser, and serves
# the deck at http://127.0.0.1:8077.
set -e
cd "$(dirname "$0")"

echo "==> ICT Trader deck — starting up (first run installs dependencies; please wait)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "!! Python 3 is not installed. Get it from https://www.python.org/downloads/ then re-run."
  read -r -p "Press Return to close." _; exit 1
fi

if [ ! -d ".venv" ]; then
  echo "==> creating local environment (.venv)…"
  python3 -m venv .venv
fi

echo "==> installing / updating the app…"
./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -e ".[serve]" >/dev/null

echo "==> opening your browser at http://127.0.0.1:8077 in a few seconds…"
( sleep 5; open "http://127.0.0.1:8077" ) &

echo "==> running the deck. Leave this window open. Press Ctrl+C here to stop."
exec ./.venv/bin/python scripts/run_all.py --no-build
