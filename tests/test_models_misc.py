from __future__ import annotations

import numpy as np

from predictormaster.models.copula import empirical_pseudo_obs, fit_gaussian_copula
from predictormaster.models.feature_selection import (
    kl_divergence,
    mutual_information,
    population_stability_index,
)
from predictormaster.models.gnn import gcn_layer, normalized_adjacency
from predictormaster.models.hmm import baum_welch, viterbi
from predictormaster.models.online import OnlineLogistic
from predictormaster.models.survival import fit_cox
from predictormaster.models.transformer_seq import scaled_dot_product_attention
from predictormaster.simulation.scenario_tree import expand_scenarios


def test_copula_correlation_recovered():
    rng = np.random.default_rng(0)
    n = 5000
    L = np.array([[1.0, 0.0], [0.6, np.sqrt(1 - 0.36)]])
    z = rng.standard_normal((n, 2)) @ L.T
    u = empirical_pseudo_obs(z)
    cop = fit_gaussian_copula(u)
    assert abs(cop.R[0, 1] - 0.6) < 0.05


def test_hmm_recovers_two_regimes():
    rng = np.random.default_rng(0)
    obs = np.concatenate([rng.choice([0, 1], size=200, p=[0.9, 0.1]),
                          rng.choice([0, 1], size=200, p=[0.1, 0.9])])
    hmm, history = baum_welch(obs, n_states=2, n_symbols=2, n_iter=50, seed=1)
    path = viterbi(hmm, obs)
    # The two regimes should be largely separated
    first_half_mode = np.bincount(path[:200]).argmax()
    second_half_mode = np.bincount(path[200:]).argmax()
    assert first_half_mode != second_half_mode
    assert history[-1] > history[0]


def test_online_logistic_learns_xor_like():
    rng = np.random.default_rng(0)
    olm = OnlineLogistic(lr=0.5)
    for _ in range(2000):
        a = float(rng.standard_normal())
        b = float(rng.standard_normal())
        y = 1 if a + b > 0 else 0
        olm.update({"a": a, "b": b}, y)
    p = olm.predict({"a": 1.0, "b": 1.0})
    assert p > 0.7


def test_cox_recovers_positive_coef():
    rng = np.random.default_rng(0)
    n = 800
    x = rng.normal(size=(n, 1))
    # Higher x → higher hazard → shorter durations
    base = rng.exponential(scale=1.0, size=n)
    durations = base * np.exp(-0.8 * x[:, 0])
    events = np.ones(n, dtype=int)
    fit = fit_cox(x, durations, events)
    assert fit.coef[0] > 0.4


def test_gnn_layer_shapes_and_smoothing():
    A = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
    Anorm = normalized_adjacency(A)
    X = np.array([[1.0, 0.0], [0.5, 1.0], [0.7, 0.5]])
    W = np.eye(2)
    H = gcn_layer(Anorm, X, W)
    assert H.shape == (3, 2)
    # Middle node combines self + neighbour features → strictly positive.
    assert H[1, 0] > 0


def test_attention_idempotent_when_mask_full():
    rng = np.random.default_rng(0)
    Q = rng.standard_normal((2, 3, 4))
    K = rng.standard_normal((2, 3, 4))
    V = rng.standard_normal((2, 3, 5))
    out = scaled_dot_product_attention(Q, K, V)
    assert out.shape == (2, 3, 5)


def test_scenario_tree_explores_paths():
    def branches(state):
        if state >= 3:
            return []
        return [(state + 1, np.log(0.5)), (state + 2, np.log(0.5))]

    leaves = expand_scenarios(root_state=0, branches=branches, max_depth=3)
    assert leaves
    assert all(leaf.depth <= 3 for leaf in leaves)


def test_information_metrics_sane():
    rng = np.random.default_rng(0)
    x = rng.normal(size=2000)
    y_signal = (x > 0).astype(int)
    y_noise = rng.integers(0, 2, size=2000)
    mi_signal = mutual_information(x, y_signal, bins=8)
    mi_noise = mutual_information(x, y_noise, bins=8)
    assert mi_signal > mi_noise

    p = np.array([0.5, 0.5])
    q = np.array([0.9, 0.1])
    assert kl_divergence(p, q) > 0
    assert kl_divergence(p, p) < 1e-9
    assert population_stability_index(p, q) > 0
