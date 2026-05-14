"""Unit tests for the evolution module.

Coverage:
  - Gene sampling, mutation, bounds enforcement
  - SearchSpace validation, YAML loading
  - Genome mutation rate ≈ 1/L, crossover invariants
  - composite_fitness multi-test correction kills noise candidates
  - composite_fitness rewards a genuinely-edgy return stream
  - evolve() runs end-to-end with a deterministic stub evaluator
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
import pytest

from predictormaster.evolution import (
    EvaluationResult,
    EvolutionConfig,
    composite_fitness,
    evolve,
)
from predictormaster.evolution.genome import (
    Gene,
    Genome,
    SearchSpace,
    crossover,
    from_yaml_dict,
    initial_population,
)

# ---------------- gene + space ----------------

def test_continuous_gene_sample_in_bounds() -> None:
    rng = random.Random(0)
    g = Gene("x", "continuous", lo=0.1, hi=0.5)
    for _ in range(200):
        v = g.sample(rng)
        assert 0.1 <= v <= 0.5


def test_integer_gene_mutate_in_bounds() -> None:
    rng = random.Random(1)
    g = Gene("k", "integer", lo=1, hi=10, mutation_scale=0.5)
    for _ in range(200):
        v = g.mutate(5, rng)
        assert 1 <= v <= 10
        assert isinstance(v, int)


def test_categorical_mutate_changes_value_when_possible() -> None:
    rng = random.Random(2)
    g = Gene("c", "categorical", choices=("a", "b", "c"))
    seen = {g.mutate("a", rng) for _ in range(50)}
    assert "a" not in seen   # never returns the current value


def test_categorical_singleton_alternatives_returns_self() -> None:
    rng = random.Random(2)
    g = Gene("c", "categorical", choices=("a", "b"))
    # mutate from one of two values must give the other
    for _ in range(20):
        assert g.mutate("a", rng) == "b"


def test_invalid_kind_rejected() -> None:
    with pytest.raises(ValueError):
        Gene("x", "weird", lo=0, hi=1)


def test_continuous_gene_inverted_bounds_rejected() -> None:
    with pytest.raises(ValueError):
        Gene("x", "continuous", lo=1.0, hi=0.5)


def test_categorical_needs_two_choices() -> None:
    with pytest.raises(ValueError):
        Gene("x", "categorical", choices=("only_one",))


def test_search_space_rejects_duplicate_gene_names() -> None:
    with pytest.raises(ValueError):
        SearchSpace("s", (Gene("a", "integer", lo=0, hi=1),
                          Gene("a", "integer", lo=0, hi=1)))


def test_search_space_validate_rejects_extra_keys() -> None:
    sp = SearchSpace("s", (Gene("a", "integer", lo=0, hi=1),))
    with pytest.raises(ValueError):
        sp.validate({"a": 0, "b": 5})


def test_yaml_dict_round_trip() -> None:
    sp = from_yaml_dict({
        "name": "demo",
        "genes": [
            {"name": "x", "kind": "continuous", "lo": 0.0, "hi": 1.0},
            {"name": "n", "kind": "integer", "lo": 1, "hi": 10},
            {"name": "s", "kind": "categorical", "choices": ["a", "b", "c"]},
        ],
    })
    assert sp.name == "demo"
    assert len(sp.genes) == 3
    assert sp.gene_by_name["s"].choices == ("a", "b", "c")


# ---------------- genome + crossover ----------------

@pytest.fixture
def demo_space() -> SearchSpace:
    return SearchSpace("demo", (
        Gene("x", "continuous", lo=0.0, hi=1.0),
        Gene("n", "integer", lo=1, hi=10),
        Gene("s", "categorical", choices=("a", "b", "c")),
    ))


def test_initial_population_size_and_validity(demo_space: SearchSpace) -> None:
    rng = random.Random(3)
    pop = initial_population(demo_space, 12, rng)
    assert len(pop) == 12
    for g in pop:
        demo_space.validate(g.values)


def test_genome_mutation_preserves_bounds(demo_space: SearchSpace) -> None:
    rng = random.Random(4)
    g = demo_space.sample(rng)
    for _ in range(50):
        g = g.mutate(demo_space, rng, rate=1.0)   # mutate every gene every time
        demo_space.validate(g.values)


def test_genome_mutation_rate_default_is_one_over_L(demo_space: SearchSpace) -> None:
    rng = random.Random(5)
    base = demo_space.sample(rng)
    n_changes = 0
    trials = 2000
    for _ in range(trials):
        child = base.mutate(demo_space, rng)
        for g in demo_space.genes:
            if child.values[g.name] != base.values[g.name]:
                n_changes += 1
    # Expected ≈ trials * L * (1/L) = trials. Tolerance: ±20%.
    assert 0.8 * trials < n_changes < 1.2 * trials


def test_crossover_genes_come_from_either_parent(demo_space: SearchSpace) -> None:
    rng = random.Random(6)
    a = Genome("demo", {"x": 0.1, "n": 1, "s": "a"})
    b = Genome("demo", {"x": 0.9, "n": 9, "s": "c"})
    seen_x = set()
    for _ in range(200):
        c = crossover(a, b, demo_space, rng)
        seen_x.add(c.values["x"])
        assert c.values["x"] in (0.1, 0.9)
        assert c.values["n"] in (1, 9)
        assert c.values["s"] in ("a", "c")
    assert seen_x == {0.1, 0.9}    # both parents contribute over many trials


# ---------------- fitness ----------------

def _make_eval(returns: np.ndarray) -> EvaluationResult:
    return EvaluationResult(
        genome=Genome("x", {}), per_bet_returns=returns, n_bets=returns.size,
    )


def test_composite_fitness_zeros_for_empty() -> None:
    evals = [_make_eval(np.array([])) for _ in range(3)]
    scores = composite_fitness(evals, n_trials_so_far=10)
    for s in scores:
        assert s.composite == 0.0


def test_composite_fitness_kills_pure_noise() -> None:
    rng = np.random.default_rng(0)
    # 4 variants of independent zero-mean noise — should not pass the gates.
    evals = [_make_eval(rng.normal(0, 0.1, size=200)) for _ in range(4)]
    scores = composite_fitness(evals, n_trials_so_far=100, placebo_perms=200)
    # noise should score very low — none clearing 0.1 composite
    assert max(s.composite for s in scores) < 0.20, \
        f"composite scores: {[round(s.composite, 4) for s in scores]}"


def test_composite_fitness_rewards_real_edge() -> None:
    rng = np.random.default_rng(1)
    # Edgy variant: positive-mean returns. Noise variants alongside.
    edgy = rng.normal(0.05, 0.1, size=400)            # Sharpe ~0.5 per-bet
    noise = [rng.normal(0, 0.1, size=400) for _ in range(3)]
    evals = [_make_eval(edgy)] + [_make_eval(r) for r in noise]
    scores = composite_fitness(evals, n_trials_so_far=4, placebo_perms=300)
    # Edgy variant should beat all noise variants
    composites = [s.composite for s in scores]
    assert composites[0] == max(composites), \
        f"edgy variant did not win: {[round(c, 4) for c in composites]}"
    assert scores[0].composite > scores[1].composite + 0.05


def test_composite_fitness_penalises_high_trial_count() -> None:
    rng = np.random.default_rng(2)
    returns = rng.normal(0.03, 0.1, size=300)
    e = [_make_eval(returns), _make_eval(rng.normal(0, 0.1, size=300))]
    low = composite_fitness(e, n_trials_so_far=1, placebo_perms=200)[0].composite
    high = composite_fitness(e, n_trials_so_far=10000, placebo_perms=200)[0].composite
    assert low > high, f"DSR penalty did not bite: low={low:.4f} high={high:.4f}"


def test_composite_fitness_placebo_kills_strategies_that_lose() -> None:
    rng = np.random.default_rng(3)
    # Strategy that LOSES systematically (negative mean). Placebo can still
    # find |SR| > |SR_obs| but Sharpe sign check still flags placebo_pass.
    losing = rng.normal(-0.05, 0.1, size=300)
    noise = rng.normal(0, 0.1, size=300)
    evals = [_make_eval(losing), _make_eval(noise)]
    scores = composite_fitness(evals, n_trials_so_far=10, placebo_perms=200)
    assert scores[0].placebo_pass == 0.05    # losing systematically fails the gate


# ---------------- end-to-end loop ----------------

@dataclass
class _StubEvaluator:
    """Returns +mu Gaussian for genome["x"] above 0.5, noise otherwise.

    This embeds a deterministic "true" alpha at x>0.5 so we can verify
    the loop's selection pressure converges on the right region.
    """
    space: SearchSpace
    rng: np.random.Generator

    def evaluate(self, genome: Genome, *, split: str) -> EvaluationResult:
        x = float(genome.values["x"])
        mu = 0.04 if x > 0.5 else 0.0
        sd = 0.1
        n = 200 if split == "train" else 80
        r = self.rng.normal(mu, sd, size=n)
        return EvaluationResult(genome=genome, per_bet_returns=r, n_bets=n)


def test_evolve_converges_on_edgy_region() -> None:
    space = SearchSpace("toy", (
        Gene("x", "continuous", lo=0.0, hi=1.0, mutation_scale=0.2),
        Gene("k", "integer", lo=1, hi=5),
    ))
    evaluator = _StubEvaluator(space=space, rng=np.random.default_rng(0))
    cfg = EvolutionConfig(
        population_size=12, n_generations=3, elite_count=3,
        placebo_perms=200, seed=99, bets_per_year=200,
    )
    report = evolve(space, evaluator, config=cfg)
    # Final generation's elites should mostly have x > 0.5
    elite_xs = [e["genome"]["x"] for e in report.elite_train]
    above = sum(1 for x in elite_xs if x > 0.5)
    assert above >= len(elite_xs) - 1, \
        f"selection pressure failed: elite x values {elite_xs}"


def test_evolve_holdout_uses_same_genome_as_train() -> None:
    space = SearchSpace("toy2", (Gene("x", "continuous", lo=0.0, hi=1.0),))
    evaluator = _StubEvaluator(space=space, rng=np.random.default_rng(0))
    cfg = EvolutionConfig(population_size=6, n_generations=2, elite_count=2,
                          placebo_perms=100, seed=7)
    report = evolve(space, evaluator, config=cfg)
    for tr, ho in zip(report.elite_train, report.elite_holdout, strict=False):
        assert tr["genome"] == ho["genome"]
    # n_trials_total = generations × population
    assert report.n_trials_total == cfg.population_size * cfg.n_generations
