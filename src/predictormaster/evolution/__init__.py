"""AlphaEvolve-style evolutionary hyperparameter search for alphas.

The methodology lesson from the α1 stress test is that any search
process — manual sweep or evolutionary — needs the multiple-testing
correction baked into its fitness function, not bolted on afterwards.
``fitness.composite_fitness`` does exactly that: deflates Sharpe by
the running trial count, kills variants whose placebo p-value is
above 0.05, and requires PBO computed across the current generation.

A pre-registered search-space YAML in ``configs/`` is loaded before
the run starts; the loop refuses to mutate parameters outside their
declared bounds. This is the firewall against "I'll just widen the
bounds when the candidate looks promising" — the single most common
way evolutionary search rediscovers noise.
"""
from .fitness import (
    EvaluationResult,
    FitnessComponents,
    composite_fitness,
)
from .genome import Gene, Genome, SearchSpace
from .loop import EvolutionConfig, EvolutionReport, evolve

__all__ = [
    "EvaluationResult",
    "EvolutionConfig",
    "EvolutionReport",
    "FitnessComponents",
    "Gene",
    "Genome",
    "SearchSpace",
    "composite_fitness",
    "evolve",
]
