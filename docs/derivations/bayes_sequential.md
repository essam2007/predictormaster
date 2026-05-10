# Sequential Bayesian Updating in Match-by-Match Posterior Inference

We have latent team-strength parameters $\theta$ and a sequence of
observations $y_1, y_2, \dots$ (matches as they finish). Bayes' theorem in
recursive form gives the *posterior at time $t$*:

$$
p(\theta \mid y_{1:t}) \;=\; \frac{p(y_t \mid \theta, y_{1:t-1}) \, p(\theta \mid y_{1:t-1})}{p(y_t \mid y_{1:t-1})}.
$$

If matches are conditionally independent given $\theta$:

$$
p(y_t \mid \theta, y_{1:t-1}) = p(y_t \mid \theta).
$$

Letting $\pi_t(\theta) = p(\theta \mid y_{1:t})$:

$$
\boxed{\;\pi_t(\theta) \;\propto\; p(y_t \mid \theta)\, \pi_{t-1}(\theta)\;}
$$

so today's posterior is yesterday's posterior re-weighted by the current
match likelihood. Two consequences for the platform:

1. **Online updates are exact** when a conjugate (or approximating)
   family is closed under the update map, e.g. Gaussian
   posteriors over team strengths under a linear-Gaussian likelihood
   (Kalman filter — see `kalman_filter.md`).
2. When no conjugate form exists, sequential Monte Carlo (the particle
   filter in `simulation/particle_filter.py`) carries weighted samples
   $\{\theta^{(i)}_{t-1}, w^{(i)}_{t-1}\}$ forward through

$$
\theta^{(i)}_t \sim q(\theta_t \mid \theta^{(i)}_{t-1}, y_t), \qquad
\tilde w^{(i)}_t \;\propto\; w^{(i)}_{t-1} \, \frac{p(\theta^{(i)}_t \mid \theta^{(i)}_{t-1}) \, p(y_t \mid \theta^{(i)}_t)}{q(\theta^{(i)}_t \mid \theta^{(i)}_{t-1}, y_t)}.
$$

## Predictive distribution

The forecast for the next match $y_{t+1}$ is obtained by marginalising:

$$
p(y_{t+1} \mid y_{1:t}) = \int p(y_{t+1} \mid \theta) \, \pi_t(\theta) \, d\theta.
$$

In our pipeline this integral is the source of *epistemic* variance; the
inner $p(y_{t+1} \mid \theta)$ supplies *aleatoric* variance. The
decomposition is what `simulation.monte_carlo.variance_decomposition`
attributes (law of total variance):

$$
\operatorname{Var}(y_{t+1} \mid y_{1:t}) =
\underbrace{\mathbb{E}_\theta[\operatorname{Var}(y_{t+1} \mid \theta)]}_{\text{aleatoric}}
+ \underbrace{\operatorname{Var}_\theta(\mathbb{E}[y_{t+1} \mid \theta])}_{\text{epistemic}}.
$$

This is *the* identity that lets us split forecast uncertainty into
"what we don't know about the world" vs "what is irreducibly random
given what we know".
