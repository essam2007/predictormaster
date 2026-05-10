# Entropy and Mutual Information for Feature Selection

## Entropy

For a discrete random variable $X$:

$$
H(X) = -\sum_x P(x) \log P(x).
$$

Properties used downstream:
* $0 \leq H(X) \leq \log |\mathcal{X}|$, max at uniform.
* Concavity in $P$.

## Mutual information

$$
I(X; Y) = \sum_{x,y} P(x, y) \log \frac{P(x, y)}{P(x) P(y)} = H(X) - H(X \mid Y) = H(Y) - H(Y \mid X).
$$

It is symmetric, non-negative, and zero iff $X \perp Y$. Unlike Pearson
correlation, mutual information detects arbitrary (non-linear, non-monotone)
dependence.

## Use as a feature score

In `models/feature_selection.py::mutual_information`, we estimate $I(X;
Y)$ via histogram binning of $X$ and the categorical $Y$. Information
gain ranking is then

$$
\mathrm{IG}(X) = I(X; Y).
$$

For correlated features we apply the conditional MI variant (mRMR; Peng et
al. 2005):

$$
J(X_k) = I(X_k; Y) - \frac{1}{|S|} \sum_{X_j \in S} I(X_k; X_j),
$$

penalising redundancy with already-selected features in $S$.

## Drift monitoring via KL and PSI

The same machinery supplies drift detection. The Population Stability
Index between train-time and serving-time feature distributions is

$$
\mathrm{PSI}(P, Q) = \sum_b (p_b - q_b) \log \frac{p_b}{q_b}.
$$

This is a symmetrised version of $\mathrm{KL}(P \,\Vert\, Q)$ — the rule
of thumb $\mathrm{PSI} > 0.2$ as the alert threshold corresponds to a
strong shift, and is the trigger configured for retraining in
`pipelines/prefect_flows.py`.

## Why this matters for valid signals

After multiple-testing correction, the surviving signals must still
contain non-zero MI with the target. A signal that survives correlation
screens but has $I(X; Y) \approx 0$ (e.g., it is correlated only with
*another* feature that happens to be predictive) will be pruned by the
mRMR ranking before model training.
