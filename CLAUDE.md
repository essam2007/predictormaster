# predictormaster — Claude Code guide

Probabilistic, multi-sport forecasting and market-efficiency research platform.
The scientific core is implemented end-to-end; the operational layer (Docker,
K8s, Terraform, Prefect, MLflow, Triton) is production-shaped scaffolding. Read
`README.md` for the full inventory of what's implemented vs. scaffolded.

## Layout

```
src/predictormaster/   scientific + serving code (models/, simulation/,
                       validation/, market/, data/, nlp/, execution/, alpha/, serving/)
dashboards/            Streamlit apps (strategy.py + pages/)
pipelines/             Prefect DAGs
infra/                 Terraform + Kubernetes
docs/                  derivations, architecture, strategy plans, pre-registration
configs/               YAML configs (data sources, model hyperparams)
tests/                 pytest suite
scripts/               runnable scripts: sweeps, stress tests, pilots, validation
outputs/               generated artifacts (sweeps, optimisation runs, results)
logs/                  run logs
ideas/                 working notes / main ideas (see ideas/README.md)
backtests/             backtest configs + outputs (see backtests/README.md)
```

## Environment

- Python >= 3.10. A `venv/` exists at the repo root.
- Install: `pip install -e ".[dev]"`. Optional extras: `ml`, `nlp`, `bayes`,
  `serving`, `pipeline`, `dashboard`, `execution` (see `pyproject.toml`).

## Commands

```bash
pytest -q                                   # test suite (excludes bench by default)
pytest -m bench --benchmark-only            # performance regression harness
ruff check .                                # lint (line-length 100, E/F/W/I/B/UP/SIM)
mypy src                                    # type check (strict_optional)
python -m predictormaster.serving.api       # local FastAPI server
streamlit run dashboards/strategy.py        # strategy dashboard
docker compose up -d                        # MLflow + feature-store + observability
```

## Conventions

- **Code style:** follow the existing module idioms. Many small, cohesive files
  over large ones. Immutable patterns; validate at boundaries (Pydantic schemas
  in `data/schemas.py`).
- **Research integrity (enforced):** pre-register hypotheses in
  `docs/pre_registration.md` before confirmatory tests. Walk-forward validation
  with an expanding window is mandatory — in-sample-only metrics are blocked at
  CI. Every model run is logged in MLflow with config hash + data version.
- **No secrets in the repo.** Every external boundary (vendor APIs, feeds) is
  mocked in tests and isolated behind an adapter; configure via env vars. See
  `.env.example`.
- **Tests are required** for new functionality; don't weaken a test to make it
  pass — fix the implementation unless the test is genuinely wrong.

## Research vault (separate)

The research thinking behind this project — hypotheses, reading notes, model
reasoning, and decisions — lives in a **separate** Obsidian vault, *Quantdude*,
at `~/Desktop/Quantdude` (`raw/` + `wiki/` layout). This repo runs independently
of it; the vault is reference material, not a runtime dependency.

- Vault-side project note: `~/Desktop/Quantdude/wiki/projects/predictormaster.md`
  (links back to this repo).
- When research here graduates into a hypothesis or decision, record it in the
  vault (`wiki/experiments/`, `wiki/decisions/`) and pre-register confirmatory
  tests in this repo's `docs/pre_registration.md`.

## Git

- Current branch: `claude/sports-forecasting-system-11m13`.
- Remote: `github.com/essam2007/predictormaster.git`.
- Commit/push only when asked. Conventional-commit style messages (the existing
  history uses `feat:`/`ops:`/`fix:` style prefixes).
