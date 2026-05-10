# Kalman Filter Predict–Update Equations from First Principles

## Linear-Gaussian state-space model

State and observation:

$$
x_{t+1} = F_t x_t + w_t, \qquad w_t \sim \mathcal{N}(0, Q_t),
$$
$$
y_t = H_t x_t + v_t, \qquad v_t \sim \mathcal{N}(0, R_t),
$$

with $w_t, v_t$ mutually independent and $x_0 \sim \mathcal{N}(\hat
x_{0|0}, P_{0|0})$.

## Predict step

Given $x_{t-1} \mid y_{1:t-1} \sim \mathcal{N}(\hat x_{t-1|t-1}, P_{t-1|t-1})$
and the linear transition, $x_t \mid y_{1:t-1}$ is the convolution of two
Gaussians, hence Gaussian with

$$
\hat x_{t|t-1} = F_t \hat x_{t-1|t-1}, \qquad
P_{t|t-1} = F_t P_{t-1|t-1} F_t^\top + Q_t.
$$

## Update step

Joint of $(x_t, y_t)$ given $y_{1:t-1}$ is Gaussian with mean
$(\hat x_{t|t-1}, H_t \hat x_{t|t-1})$ and covariance

$$
\Sigma = \begin{bmatrix} P_{t|t-1} & P_{t|t-1} H_t^\top \\ H_t P_{t|t-1} & H_t P_{t|t-1} H_t^\top + R_t \end{bmatrix}.
$$

The conditional Gaussian formula gives

$$
x_t \mid y_{1:t} \sim \mathcal{N}(\hat x_{t|t}, P_{t|t})
$$

with

$$
S_t = H_t P_{t|t-1} H_t^\top + R_t,
$$
$$
K_t = P_{t|t-1} H_t^\top S_t^{-1},
$$
$$
\hat x_{t|t} = \hat x_{t|t-1} + K_t (y_t - H_t \hat x_{t|t-1}),
$$
$$
P_{t|t} = (I - K_t H_t) P_{t|t-1}.
$$

The matrix $K_t$ is the Kalman gain; $y_t - H_t \hat x_{t|t-1}$ is the
innovation; $S_t$ is the innovation covariance.

## Why this matches `models/kalman.py`

`KalmanFilter.predict` advances $(\hat x, P)$ exactly by
$F \hat x$ and $F P F^\top + Q$. `KalmanFilter.update` computes $S$, $K$,
and applies the two boxed lines above. The Joseph-form covariance update is
not used because $(I - K H) P$ is sufficient when matrices are
well-conditioned, and our $P$ matrices are small (one per league).

## Optimality

Among **all** estimators of $x_t$ that are linear in $y_{1:t}$ and
unbiased, the Kalman filter has the minimum mean-square error. Under the
Gaussian assumption it is the *exact* posterior mean, not just the best
linear estimator.
