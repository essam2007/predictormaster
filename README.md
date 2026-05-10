# predictormaster

Probabilistic, multi-sport forecasting and market-efficiency research platform.

This repository implements the scientific core of the system end-to-end and
provides production-shaped scaffolding (Docker, Kubernetes, Terraform, Prefect,
MLflow, Triton) for the operational layer. It is structured so that the
mathematical components can be peer-reviewed in isolation while the deployment
layer can be audited as infrastructure.

## What is fully implemented

- Dixon-Coles bivariate Poisson with low-score correlation correction and MLE
  estimation (`src/predictormaster/models/dixon_coles.py`)
- Elo and Glicko-2 online rating systems (`models/elo.py`, `models/glicko.py`)
- Linear-Gaussian Kalman filter for latent team-strength tracking
  (`models/kalman.py`)
- Bayesian hierarchical Poisson model (NumPy/SciPy MAP + Laplace posterior with
  optional PyMC backend) (`models/bayesian_hierarchical.py`)
- Hidden Markov Model with Baum-Welch EM (`models/hmm.py`)
- Sparse-GP form curve estimator with RBF kernel (`models/gp_form.py`)
- Gaussian copula for cross-player joint dependency (`models/copula.py`)
- Cox proportional hazards survival model (`models/survival.py`)
- Gradient boosting ensemble wrapper (XGBoost + LightGBM stack) with
  monotonicity constraints and SHAP hooks (`models/gbm_ensemble.py`)
- Online Elo + Vowpal-Wabbit-style logistic SGD (`models/online.py`)
- Stacked meta-learner with elastic-net regularisation (`models/meta_ensemble.py`)
- Possession-level Monte Carlo simulator, vectorised; particle filter for
  non-Gaussian state-space; scenario tree (`simulation/`)
- ECE / MCE, Brier-score Murphy decomposition, Brier Skill Score, reliability
  diagrams, walk-forward CV with expanding window (`validation/`)
- Page-Hinkley and ADWIN-style drift detectors (`validation/drift.py`)
- Event-study, panel regression with HC3 and BH-FDR for market efficiency
  (`market/efficiency.py`)
- Population Stability Index, KL divergence, entropy/MI feature scoring
  (`validation/calibration.py`, `models/feature_selection.py`)
- Point-in-time feature store interface with leakage guards
  (`data/feature_store.py`)
- Great-Expectations-style data quality assertions (`data/quality.py`)
- Pydantic schemas for every record class (`data/schemas.py`)

## What is scaffolded with clean interfaces

These components have working module boundaries, type contracts, and unit
tests for the parts that don't require external accounts, but the actual
deployed inference servers / clusters / vendor APIs have to be provisioned
separately.

- Triton inference config and gRPC client (`serving/triton/`)
- Transformer-based sequence model (HuggingFace head, training loop)
  (`models/transformer_seq.py`)
- Graph Neural Network on player-team-opponent graph (PyG-compatible)
  (`models/gnn.py`)
- Sports-domain BERT sentiment classifier and BERTopic dynamic topics
  (`nlp/sentiment.py`, `nlp/topics.py`)
- Reinforcement-learning lineup agent (`models/rl_lineup.py`)
- Kafka / Redpanda streaming ingestion, ESPN / X / Reddit adapters
  (`data/ingestion/*`)
- Prefect orchestration DAG (`pipelines/prefect_flows.py`)
- Terraform skeleton for EKS + Triton (`infra/terraform/`)
- Kubernetes manifests with HPA (`infra/k8s/`)
- GitHub Actions CI with calibration / drift gating (`.github/workflows/ci.yml`)
- MLflow + Great-Expectations service definitions (`docker-compose.yml`)

## What is intentionally not in this repo

Live API keys, vendor data, and any cloud account state. Every external
boundary is mocked in tests and isolated behind an adapter so the platform can
be brought up against real feeds by setting environment variables.

## Mathematical derivations

All ten derivations required by the research charter are in `docs/derivations/`
and are written so they are self-contained from first principles.

## Latency and SLA targets

See `docs/architecture.md` for the annotated diagram with latency budgets per
edge and `docs/slas.md` for ingestion / inference / training SLAs.

## Running

```bash
pip install -e ".[dev]"
pytest -q
python -m predictormaster.serving.api  # local FastAPI server
docker compose up -d                   # MLflow + feature-store + observability
```

## Research integrity

- Hypotheses are pre-registered in `docs/pre_registration.md` before
  confirmatory tests are run.
- Every model run is logged in MLflow with config hash and data version.
- Walk-forward validation is mandatory; in-sample-only metrics are blocked at
  CI.

## Layout

```
src/predictormaster/   scientific + serving code
pipelines/             Prefect DAGs
infra/                 Terraform + Kubernetes
docs/                  derivations, architecture, paper draft
tests/                 pytest suite
configs/               YAML configs (data sources, model hyperparams)
```
