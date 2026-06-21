#!/bin/bash
# SessionStart hook: bootstrap the ict_trader subproject so Claude Code on the web can run
# ruff / mypy / pytest and the vite build immediately. Idempotent and non-interactive.
set -euo pipefail

# Only bootstrap in remote (Claude Code on the web) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
APP="$ROOT/ict_trader"
[ -d "$APP" ] || exit 0
cd "$APP"

# Python: venv + the pure core, serve (API/DB) and dev (ruff/mypy/pytest) extras.
# Prefer uv (how this venv was built); fall back to stdlib venv + pip.
if command -v uv >/dev/null 2>&1; then
  [ -d .venv ] || uv venv .venv
  uv pip install --quiet --python .venv/bin/python -e ".[serve,dev]"
else
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -e ".[serve,dev]"
fi

# Frontend: deps for `npm run build` (tsc + vite). install (not ci) to reuse the cache.
if [ -d frontend ]; then
  ( cd frontend && npm install --no-fund --no-audit --silent )
fi

echo "ict_trader bootstrap complete (venv + serve/dev extras + frontend deps)."
