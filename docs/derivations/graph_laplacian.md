# Graph Laplacian and Spectral Message Passing

## Definition

For a weighted undirected graph $G = (V, E, W)$ with adjacency $A$ and
degree matrix $D = \mathrm{diag}(d_1, \dots, d_n)$, the *combinatorial
Laplacian* is

$$
L = D - A.
$$

The *symmetric normalised Laplacian* is

$$
L_{\mathrm{sym}} = D^{-1/2} L D^{-1/2} = I - D^{-1/2} A D^{-1/2}.
$$

## Quadratic form

For any signal $x \in \mathbb{R}^n$,

$$
x^\top L x = \tfrac{1}{2} \sum_{(i,j) \in E} A_{ij} (x_i - x_j)^2 \geq 0,
$$

so $L$ is positive semi-definite. Eigenvalues
$0 = \lambda_1 \leq \lambda_2 \leq \dots \leq \lambda_n$. The
multiplicity of zero equals the number of connected components.

## Graph Fourier transform

Diagonalise $L = U \Lambda U^\top$. The graph Fourier transform of
$x$ is $\hat x = U^\top x$. A *spectral filter*
$g_\theta(\Lambda) = \mathrm{diag}(g_\theta(\lambda_1), \dots, g_\theta(\lambda_n))$
acts as $y = U g_\theta(\Lambda) U^\top x$.

Computing $U$ is $O(n^3)$. Kipf & Welling approximated $g_\theta$ by a
first-order Chebyshev polynomial in $L_{\mathrm{sym}}$:

$$
g_\theta(L_{\mathrm{sym}}) \approx \theta_0 I + \theta_1 (L_{\mathrm{sym}} - I) = \theta_0 I - \theta_1 D^{-1/2} A D^{-1/2}.
$$

Tying $\theta = \theta_0 = -\theta_1$ gives the standard GCN propagation rule:

$$
H^{(\ell+1)} = \sigma\big( \tilde D^{-1/2} \tilde A \tilde D^{-1/2} H^{(\ell)} W^{(\ell)} \big), \qquad \tilde A = A + I.
$$

That is exactly what `models/gnn.py::gcn_layer` computes (with `normalized_adjacency`
producing $\tilde D^{-1/2} \tilde A \tilde D^{-1/2}$).

## Why this is the right inductive bias for sports graphs

Players, teams, and matches form a heterogeneous graph where information
should propagate along genuine relations (teammate, opponent, played-in).
Spectral message passing penalises high-frequency components on the
graph — i.e., it smooths over densely-connected subgraphs while
preserving variation across loosely-connected ones. Attack/defence
strengths are exactly low-frequency modes; player-specific deviations are
the high-frequency residuals we want to learn separately.
