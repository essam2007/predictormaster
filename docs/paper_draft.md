# Paper Draft Skeleton — "Multi-Modal Probabilistic Forecasting in Sports Markets"

Target venues: Journal of Quantitative Analysis in Sports; Quantitative
Economics; Journal of Forecasting.

## Title (working)

Calibrated Multi-Modal Probabilistic Forecasting in Sports Markets:
Statistical Lift, Latency, and Information Incorporation

## Abstract (≤ 250 words)

We design and deploy a multi-sport probabilistic forecasting system that
combines structural statistical models (Dixon-Coles, Bayesian
hierarchical Poisson, Kalman filters) with gradient-boosted ensembles, a
fine-tuned transformer over event sequences, and a graph neural network
over player-team-opponent graphs. We pre-register five hypotheses on
multi-modal lift, information-incorporation speed, crowd alpha,
regime-shift detection, and end-to-end NLP latency, and evaluate them on
walk-forward holdouts covering [N] seasons across [K] sports. We find
[result placeholders, populated post-analysis]. Calibration ECE and
Brier-skill-score-vs-market are tracked weekly and gate model
promotion in production.

## 1. Introduction

* The forecasting question and why latency matters.
* Tension between statistical rigour and operational latency.
* Contribution: a unified architecture demonstrating both.

## 2. Data

* Source-by-source SLA table (cross-reference `docs/slas.md`).
* Survivorship-bias remediation, leakage audits, point-in-time joins.
* Schema versioning and reproducibility (DVC + Delta Lake).

## 3. Models

### 3.1 Structural layer

Dixon-Coles, Bayesian hierarchical Poisson, Kalman filter (full
derivations in supplementary material).

### 3.2 ML layer

Gradient-boosting ensemble, transformer sequence model, GNN, online
learner, stacked meta-ensemble.

### 3.3 NLP layer

Sentiment, dynamic topic model, narrative-velocity, contagion graph.

## 4. Validation methodology

* Walk-forward CV with $\geq$ 2-season burn-in.
* Brier decomposition and BSS against climatological + market baselines.
* HC3 panel regressions, Benjamini-Hochberg FDR.

## 5. Results

* Tabular results per sport and per fold, with bootstrap CIs.
* Reliability diagrams.
* Latency distributions.
* Event-study figures.

## 6. Market efficiency

* Information incorporation curves.
* Reflexivity test using consensus delta as instrument.

## 7. Engineering reproducibility

* Container hashes, data version, MLflow run IDs for every figure.
* Cost per prediction and training-pipeline cost.

## 8. Limitations

* External validity: leagues studied; non-stationarity outside the
  training window.
* Model uncertainty separately quantified, not merged into outcome
  variance.

## 9. Conclusion

## Supplementary material

* Full derivations (`docs/derivations/`).
* Pre-registration document.
* All code, hyperparameter configs, and Docker pinning.
