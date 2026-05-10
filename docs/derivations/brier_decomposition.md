# Brier Score Decomposition (Murphy 1973)

For a binary outcome $y \in \{0, 1\}$ and a probability forecast $f \in
[0, 1]$, the Brier score is

$$
\mathrm{BS} = \frac{1}{N} \sum_{i=1}^N (f_i - y_i)^2.
$$

Group forecasts into $K$ bins with $n_k$ samples each, mean forecast
$\bar f_k$, observed frequency $\bar o_k$, and overall mean $\bar o$.
Algebraic identity:

$$
(f_i - y_i)^2 = (f_i - \bar o_k)^2 + (\bar o_k - y_i)^2 + 2(f_i - \bar o_k)(\bar o_k - y_i).
$$

Sum over bin $k$. The cross term collapses because
$\sum_{i \in k} (\bar o_k - y_i) = 0$. Therefore

$$
\sum_{i \in k} (f_i - y_i)^2 = n_k (\bar f_k - \bar o_k)^2 + \sum_{i \in k} (\bar o_k - y_i)^2.
$$

For the second piece, expanding around $\bar o$:

$$
\sum_{i \in k} (\bar o_k - y_i)^2 = n_k (\bar o_k - \bar o)^2 + \sum_{i \in k} (\bar o - y_i)^2 - 2 n_k (\bar o_k - \bar o)(\bar o - \bar o)
$$

The last term vanishes; summing the residual over $k$ gives $\sum_i
(\bar o - y_i)^2 = N \bar o (1 - \bar o)$.

Dividing through by $N$:

$$
\boxed{\;\mathrm{BS} \;=\; \underbrace{\tfrac{1}{N}\sum_k n_k (\bar f_k - \bar o_k)^2}_{\text{REL (reliability)}} \;-\; \underbrace{\tfrac{1}{N}\sum_k n_k (\bar o_k - \bar o)^2}_{\text{RES (resolution)}} \;+\; \underbrace{\bar o (1 - \bar o)}_{\text{UNC (uncertainty)}}.\;}
$$

## Interpretation

* REL: how far each bin's average forecast deviates from realised
  frequency. **Lower is better.** A perfectly calibrated forecaster has
  REL = 0.
* RES: how far each bin's realised frequency deviates from the
  unconditional base rate. **Higher is better.** A skillful forecaster
  separates outcomes well.
* UNC: irreducible variance of the binary target itself. Independent of
  the forecaster.

Brier Skill Score is then $\mathrm{BSS} = 1 - \mathrm{BS}/\mathrm{UNC}$
relative to the climatological baseline; we also track BSS against the
market-implied baseline as a separate skill metric.

This identity is implemented exactly in
`validation/calibration.py::brier_decomposition` and is the basis of the
calibration gate used in CI.
