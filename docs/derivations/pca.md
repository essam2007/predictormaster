# Eigenvalue Analysis of the Covariance Matrix in PCA Compression

Given centred data $X \in \mathbb{R}^{N \times p}$ (rows are observations,
columns are tracking-feature dimensions), the empirical covariance is

$$
\Sigma = \tfrac{1}{N-1} X^\top X.
$$

PCA finds an orthonormal basis $u_1, \dots, u_p$ that successively
maximise variance:

$$
u_1 = \arg\max_{\|u\|=1} u^\top \Sigma u, \qquad
u_k = \arg\max_{\|u\|=1,\, u \perp u_{<k}} u^\top \Sigma u.
$$

## Lagrangian and the eigenproblem

The Lagrangian is $\mathcal{L}(u, \lambda) = u^\top \Sigma u - \lambda(u^\top u - 1)$.
Stationarity:

$$
\nabla_u \mathcal{L} = 2 \Sigma u - 2 \lambda u = 0 \;\;\Rightarrow\;\; \Sigma u = \lambda u.
$$

So the principal axes are eigenvectors of $\Sigma$ and the Lagrange
multipliers are the corresponding eigenvalues. The maximised variance
along direction $u_k$ is $u_k^\top \Sigma u_k = \lambda_k$.

## Compression bound

Project $X$ onto the top $r$ eigenvectors $U_r$ to obtain $Z = X U_r$. The
reconstruction $\hat X = Z U_r^\top$ has expected squared error

$$
\mathbb{E}\|x - \hat x\|^2 = \sum_{k=r+1}^p \lambda_k.
$$

Choosing $r$ to satisfy $\sum_{k \leq r} \lambda_k / \sum_k \lambda_k \geq
\eta$ retains a fraction $\eta$ of variance.

## Why we use it on tracking data

Player-tracking data in basketball/soccer is high-dimensional (positions
of 10–22 players sampled at 25Hz). Empirically, the top ~30 components
explain >95% of variance. Compressing here saves training and serving
cost while preserving the spectral structure that downstream sequence
and graph models depend on.

Numerical implementation: SVD of $X$, $X = U \Sigma V^\top$, with $V$
giving the eigenvectors of $X^\top X$ and $\Sigma_{kk}^2 / (N-1)$ giving
the eigenvalues. SVD is preferred over forming $\Sigma$ explicitly to
avoid the $\kappa(\Sigma) = \kappa(X)^2$ conditioning blow-up.
