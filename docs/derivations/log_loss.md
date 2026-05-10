# Log-Loss as a Strictly Proper Scoring Rule via KL Divergence

A scoring rule $S(P, y)$ assigns a score to a probabilistic forecast $P$
on observed outcome $y$. We say $S$ is *proper* if a forecaster minimises
their *expected* score by reporting their honest belief $Q$:

$$
\mathbb{E}_{y \sim Q}[S(P, y)] \geq \mathbb{E}_{y \sim Q}[S(Q, y)] \qquad \forall P,
$$

with equality iff $P = Q$ (strict propriety).

## Log-loss

Define $S_{\log}(P, y) = -\log P(y)$. Then

$$
\mathbb{E}_{y \sim Q}[S_{\log}(P, y)] - \mathbb{E}_{y \sim Q}[S_{\log}(Q, y)]
= \sum_y Q(y) \log \frac{Q(y)}{P(y)} = \mathrm{KL}(Q \,\Vert\, P) \geq 0,
$$

with equality iff $P = Q$. So log-loss is **strictly proper**, with the
expected-score gap equal to the KL divergence from the true distribution to
the report.

## Why this matters operationally

1. **Honest forecasts are optimal.** Any model trained to minimise log-loss
   has no incentive (in expectation) to under- or over-state confidence.
2. **The achievable floor is the entropy of the truth.** The minimum
   expected log-loss is $H(Q) = -\sum_y Q(y) \log Q(y)$. We track this
   in `validation.calibration` as the *uncertainty* term in the Brier
   decomposition's entropy analogue.
3. **It composes with calibration.** Log-loss decomposes into a calibration
   term and a refinement term in the same way the Brier score does
   (Murphy 1973). Both metrics are kept in CI dashboards.

## Connection to MLE

Maximum-likelihood training is exactly empirical-log-loss minimisation, so
the entire statistical layer (Dixon-Coles, hierarchical Poisson, GBM
softmax, transformer cross-entropy) is consistent under this proper
scoring rule.
