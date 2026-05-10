# Dixon-Coles MLE with Low-Score Correlation Correction

## Likelihood

For a match $i$ between home team $h$ and away team $a$, with goals
$x_i, y_i$:

$$
\lambda_i = \exp(\alpha_h + \beta_a + \gamma), \qquad
\mu_i     = \exp(\alpha_a + \beta_h),
$$

with attack vector $\alpha$, defence vector $\beta$, and home advantage
$\gamma$. Subject to identifiability $\sum_t \alpha_t = 0$.

The bivariate Poisson with low-score correction is

$$
P(X=x, Y=y) = \tau(x, y;\,\lambda, \mu, \rho) \, \frac{e^{-\lambda} \lambda^x}{x!} \, \frac{e^{-\mu} \mu^y}{y!},
$$

where

$$
\tau(0,0)=1-\lambda \mu \rho, \quad \tau(0,1)=1+\lambda\rho, \quad
\tau(1,0)=1+\mu\rho, \quad \tau(1,1)=1-\rho,
$$

and $\tau(x,y)=1$ otherwise. The constraint $\rho \in (-\min(1, 1/(\lambda\mu)),\, \min(1/\lambda, 1/\mu))$ keeps every $\tau(x,y) > 0$.

## Log-likelihood

With temporal weights $w_i = e^{-\xi \Delta t_i}$ (Dixon-Coles down-weight):

$$
\ell(\theta) = \sum_i w_i \Big[\log \tau(x_i, y_i;\lambda_i, \mu_i, \rho)
+ x_i \log \lambda_i - \lambda_i - \log x_i!
+ y_i \log \mu_i - \mu_i - \log y_i!\Big].
$$

## Score function

For a parameter $\phi$ with $\partial_\phi \log\lambda = u$, $\partial_\phi \log\mu = v$:

$$
\partial_\phi \ell = \sum_i w_i \Big[\frac{\partial_\phi \tau_i}{\tau_i} + (x_i - \lambda_i) u_i + (y_i - \mu_i) v_i\Big].
$$

The Poisson part $(x - \lambda) u + (y - \mu) v$ is the standard
generalised-linear-model score. The first term is the Dixon-Coles
correction; explicitly, for the four corner cells:

$$
\partial_\rho \log \tau(0,0) = \frac{-\lambda \mu}{1 - \lambda \mu \rho},
\qquad
\partial_\rho \log \tau(0,1) = \frac{\lambda}{1 + \lambda \rho},
$$
$$
\partial_\rho \log \tau(1,0) = \frac{\mu}{1 + \mu \rho},
\qquad
\partial_\rho \log \tau(1,1) = \frac{-1}{1 - \rho}.
$$

## Identifiability

Without the sum-to-zero constraint, $\alpha \to \alpha + c$, $\beta \to
\beta - c$, $\gamma \to \gamma$ leaves $\lambda$ unchanged but shifts $\mu$
by $-c$, so $\alpha$ and $\beta$ are not separately identified. We pin
$\alpha_T = -\sum_{t<T} \alpha_t$ in `_unpack`, removing one degree of
freedom and giving an interior maximum.

## Computational complexity

The negative log-likelihood is $O(N)$ in the number of matches and
$O(T)$ in teams (the index gather). L-BFGS-B converges in 30–80
iterations on a top-five-leagues dataset. Inference (intensities and
score PMF) is $O(K^2)$ for max goal $K$.
