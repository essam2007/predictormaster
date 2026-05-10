# ELBO Derivation for Variational Inference

We approximate an intractable posterior $p(\theta \mid y)$ with $q_\phi(\theta)$
indexed by variational parameters $\phi$. By Jensen's inequality:

$$
\log p(y) = \log \int p(y, \theta)\, d\theta
        = \log \int q_\phi(\theta) \frac{p(y, \theta)}{q_\phi(\theta)}\, d\theta
        \geq \int q_\phi(\theta) \log \frac{p(y, \theta)}{q_\phi(\theta)}\, d\theta.
$$

The right-hand side is the *evidence lower bound* (ELBO):

$$
\boxed{\; \mathcal{L}(\phi) \;=\; \mathbb{E}_{q_\phi}[\log p(y, \theta)] \;-\; \mathbb{E}_{q_\phi}[\log q_\phi(\theta)]. \;}
$$

## Equivalent decompositions

Reconstruction + KL:

$$
\mathcal{L}(\phi) = \mathbb{E}_{q_\phi}[\log p(y \mid \theta)] - \mathrm{KL}(q_\phi(\theta) \,\Vert\, p(\theta)).
$$

Posterior gap:

$$
\log p(y) - \mathcal{L}(\phi) = \mathrm{KL}(q_\phi(\theta) \,\Vert\, p(\theta \mid y)) \geq 0,
$$

so maximising the ELBO is equivalent to minimising
$\mathrm{KL}(q_\phi \,\Vert\, p(\theta \mid y))$. The bound is tight iff
$q_\phi = p(\theta \mid y)$.

## Mean-field for hierarchical Poisson

For the model in `models/bayesian_hierarchical.py`,

$$
q_\phi(\alpha, \beta, \gamma, \sigma_a, \sigma_b) = q(\alpha) q(\beta) q(\gamma) q(\sigma_a) q(\sigma_b),
$$

with $q(\alpha)$ a diagonal Gaussian of dimension $T$ (one per team), etc.
The reparameterisation trick $\alpha = m + s \odot \epsilon$ ($\epsilon \sim
\mathcal{N}(0, I)$) makes the ELBO a pathwise differentiable function of
$\phi = (m, s, \dots)$, suitable for SGD/Adam.

When the variational family contains the true posterior, ELBO maximisation
recovers it exactly. In all other cases — including the strongly non-
Gaussian Dixon-Coles posterior with the four corner cells — the mean-field
ELBO underestimates posterior variance, motivating either structured
variational families or full NUTS as a benchmark.

## Why the platform supports both VI and MCMC

VI is fast enough to run inline in CI for sanity-checking parameter shifts
between champion and challenger models; NUTS is reserved for the weekly
scheduled retrain when the marginal cost of an extra hour of compute is
negligible compared to the calibration risk of biased posteriors.
