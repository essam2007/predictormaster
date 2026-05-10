# Ornstein-Uhlenbeck Process for Continuous-Time Team Strength

We model team strength $\theta_t$ as the SDE

$$
d\theta_t = \kappa(\mu - \theta_t) \, dt + \sigma \, dW_t,
$$

with mean-reversion speed $\kappa > 0$, long-run mean $\mu$, volatility
$\sigma > 0$, and Wiener noise $W_t$. This is the Ornstein-Uhlenbeck
process.

## Closed-form transition density

Solving the linear SDE by Itô's lemma applied to $f(\theta, t) = \theta e^{\kappa t}$:

$$
\theta_t = \mu + (\theta_0 - \mu) e^{-\kappa t} + \sigma \int_0^t e^{-\kappa(t - s)} dW_s.
$$

Hence

$$
\theta_t \mid \theta_0 \sim \mathcal{N}\!\left(\mu + (\theta_0 - \mu) e^{-\kappa t}, \; \frac{\sigma^2}{2\kappa}(1 - e^{-2\kappa t})\right).
$$

## Half-life of skill information

The deterministic part decays exponentially with rate $\kappa$, so the
half-life of any *deviation from the long-run mean* is

$$
t_{1/2} = \frac{\ln 2}{\kappa}.
$$

In our retrain scheduler this is the mathematical justification for
weekly retrains in basketball ($t_{1/2} \approx 30\text{–}40$ days
empirically) versus daily retrains in tennis (single-match injuries
shorten effective $t_{1/2}$).

## Stationary distribution

Letting $t \to \infty$:

$$
\theta_\infty \sim \mathcal{N}\!\left(\mu, \frac{\sigma^2}{2\kappa}\right).
$$

So the variance of long-run strength scales with $\sigma^2$ and inversely
with the mean-reversion speed — a faster reverting league has tighter
talent dispersion.

## Discretisation matching the Kalman filter

The exact transition above is linear-Gaussian, so the discrete-time
state model

$$
\theta_{t+\Delta} = (1 - e^{-\kappa\Delta}) \mu + e^{-\kappa\Delta} \theta_t + \eta_t, \qquad
\eta_t \sim \mathcal{N}(0, \tfrac{\sigma^2}{2\kappa}(1 - e^{-2\kappa\Delta})),
$$

is *exact*, not an approximation. This is why the Kalman filter in
`models/kalman.py` can hold the closed-form posterior at every step with
no discretisation bias, given $F = e^{-\kappa\Delta}$ and
$Q = \tfrac{\sigma^2}{2\kappa}(1 - e^{-2\kappa\Delta}) I$.

## Identifiability

$\kappa, \mu, \sigma$ are all identified given $\geq 2$ observations of
$\theta$ at distinct lags. We estimate $(\kappa, \sigma)$ by maximum
likelihood on the residual sequence and treat $\mu$ as a sport-level
hyperparameter (zero on standardised strength).
