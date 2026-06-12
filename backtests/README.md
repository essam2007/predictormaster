# backtests

Backtest definitions and their outputs.

- Keep each backtest's config + result together (or reference a config in
  `configs/`).
- Walk-forward validation with an expanding window is mandatory; in-sample-only
  metrics are blocked at CI. See `src/predictormaster/validation/`.
- Larger generated artifacts (sweeps, optimisation runs) live in `outputs/` and
  `scripts/` — link to them from here rather than duplicating.
