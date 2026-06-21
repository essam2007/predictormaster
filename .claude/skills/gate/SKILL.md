---
name: gate
description: Run the full ict_trader quality gate — ruff + mypy (strict) + pytest, then the frontend build (tsc + vite) and rebuild dist. Use before committing or when asked to verify the project is green.
---

# /gate — ict_trader quality gate

Run the project's full quality gate and report pass/fail concisely. Stop and surface the
first failure with its output rather than pushing through.

## Steps (run from the repo root)

1. **Python lint + types + tests** (the venv is bootstrapped by the SessionStart hook):
   ```bash
   cd ict_trader && source .venv/bin/activate \
     && ruff check src tests scripts \
     && mypy src \
     && pytest
   ```
2. **Frontend build** (type-check + production bundle; commit the rebuilt dist if it changed):
   ```bash
   cd ict_trader/frontend && npm run build
   ```

## Reporting
- Summarize each stage as ✅/❌ with the counts (ruff clean, mypy file count, tests passed).
- The pre-existing sports `test` GitHub workflow (ruff N806 in the sports code) is OUT OF
  SCOPE — do not try to fix it; the relevant CI is the `ict-trader` workflow.
- If everything passes and dist changed, remind to commit `frontend/dist/`.
