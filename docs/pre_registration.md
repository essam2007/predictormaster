# Pre-Registration of Confirmatory Hypotheses

This document is committed *before* the corresponding analyses are run.
Any deviation must be documented in `docs/deviations.md` with a
justification, and the original hypothesis is retained in the record.

## H1 — Multi-modal lift

**Hypothesis.** A meta-ensemble augmented with NLP sentiment, narrative-
velocity, and consensus-entropy features achieves a Brier-skill-score
improvement of ≥ 0.02 (absolute) over the structural-only baseline,
across walk-forward folds covering ≥ 2 full seasons in each of basketball,
soccer, and American football.

**Test.** Paired bootstrap of fold-level BSS deltas; reject the null at
$\alpha = 0.05$ after Benjamini-Hochberg correction across the three
sports.

**Failure mode.** If lift is < 0.005, the multi-modal architecture is
removed from the production stack.

## H2 — Information incorporation speed

**Hypothesis.** The cross-platform consensus stabilises (mean abnormal
move below 5 percentage points) within ≤ 12 minutes of injury-news
release, with no statistically significant lag for high-prominence vs
low-prominence players.

**Test.** Event-study CAR with cluster-robust SE, two-sample t-test on
stabilisation times by prominence tier.

## H3 — Crowd alpha after costs

**Hypothesis.** Cross-platform consensus disagreement (entropy ≥ 75th
percentile) correlates with subsequent forecast residual variance
($\rho > 0.05$) after controlling for sport and competition fixed effects.

**Test.** Panel regression with HC3 SEs (`market.efficiency.panel_regression_hc3`).

## H4 — Sub-minute regime shift

**Hypothesis.** A Page-Hinkley detector on rolling residuals raises an
alert within 60 seconds (median) of an injected regime shift in
back-tested injury-impact scenarios.

**Test.** Synthetic injection at known timestamps; detection latency
distribution vs an 60 s SLA.

## H5 — Sentiment within 500 ms

**Hypothesis.** End-to-end pipeline latency from social post arrival to
sentiment feature availability in the online store is ≤ 500 ms at p95
under sustained 5k posts/sec load.

**Test.** Production load test with synthetic firehose; report
distribution of (timestamp_post → timestamp_feature) durations.

## Non-confirmatory analyses

All exploratory analyses are explicitly marked in code with the
`# EXPLORATORY` comment and excluded from the confirmatory FDR
correction set.
