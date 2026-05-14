"""Evolutionary loop: tournament selection + elitism + crossover + mutation.

Why this and not simulated annealing or CMA-ES:
  - GA mutate/crossover is trivially parallelisable across population
    members and we expect to scale evaluators (the slow step) before
    we scale the search algorithm itself.
  - Tournament selection is robust to fitness-scale outliers — a
    single absurdly-high evaluation cannot dominate the next gen,
    which matters because the multi-test correction in fitness.py
    occasionally lets a low-trial-count fluke through.
  - CMA-ES would be a better choice ONCE we have ≥6 continuous genes
    and confidence that the fitness surface is locally Gaussian.
    Neither is true today.

Hold-out protocol
-----------------
The evaluator receives a ``train_split`` and a ``holdout_split``
indicator and is contractually required to use *only* the train fold
during evolution. After the final generation, the loop re-evaluates
the elite genomes on the holdout fold and reports both sets of
fitness components. A wide train→holdout gap in composite fitness is
the clearest possible signal of overfit-the-validation-set.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .fitness import EvaluationResult, FitnessComponents, composite_fitness
from .genome import Genome, SearchSpace, crossover, initial_population

logger = logging.getLogger(__name__)


class Evaluator(Protocol):
    """Strategy-specific evaluator. Returns per-bet returns under the
    given hyperparameters, evaluated against the requested split."""
    def evaluate(self, genome: Genome, *, split: str) -> EvaluationResult: ...


@dataclass(frozen=True)
class EvolutionConfig:
    population_size: int = 24
    n_generations: int = 5
    elite_count: int = 4
    tournament_size: int = 3
    mutation_rate: float | None = None   # None ⇒ 1/L per gene
    placebo_perms: int = 1000
    fee_per_bet: float = 0.02
    bets_per_year: int = 200
    seed: int = 42


@dataclass
class GenerationRecord:
    generation: int
    best_genome: dict
    best_fitness: dict
    median_composite: float
    n_trials_so_far: int
    population: list[dict] = field(default_factory=list)


@dataclass
class EvolutionReport:
    config: dict
    search_space_name: str
    started_utc: str
    finished_utc: str
    generations: list[GenerationRecord]
    elite_train: list[dict]              # train-fold final fitness
    elite_holdout: list[dict]            # hold-out evaluation of the same elites
    n_trials_total: int

    def to_json(self) -> str:
        def _enc(o):
            if hasattr(o, "to_dict"):
                return o.to_dict()
            if isinstance(o, GenerationRecord):
                return o.__dict__
            raise TypeError(repr(o))
        return json.dumps(self.__dict__, indent=2, default=_enc)


def _tournament_pick(
    population: list[Genome],
    scores: list[FitnessComponents],
    k: int,
    rng: random.Random,
) -> Genome:
    idxs = rng.sample(range(len(population)), k=min(k, len(population)))
    best_i = max(idxs, key=lambda i: scores[i].composite)
    return population[best_i]


def _diversify(population: list[Genome], space: SearchSpace, rng: random.Random) -> list[Genome]:
    """If duplicates have appeared (cheap symptom of collapse), replace
    them with fresh random samples. We keep the first occurrence."""
    seen: set[tuple] = set()
    out: list[Genome] = []
    for g in population:
        key = tuple(sorted(g.values.items()))
        if key in seen:
            out.append(space.sample(rng))
        else:
            seen.add(key)
            out.append(g)
    return out


def evolve(
    space: SearchSpace,
    evaluator: Evaluator,
    *,
    config: EvolutionConfig | None = None,
    log_path: Path | None = None,
) -> EvolutionReport:
    """Run the evolutionary loop.

    The evaluator is called with ``split="train"`` during evolution
    and ``split="holdout"`` once per elite at the end. The evaluator
    is responsible for partitioning its own dataset accordingly.
    """
    if config is None:
        config = EvolutionConfig()
    started = datetime.now(timezone.utc).isoformat()
    rng = random.Random(config.seed)
    population = initial_population(space, config.population_size, rng)
    n_trials_so_far = 0

    gen_records: list[GenerationRecord] = []

    for gen in range(config.n_generations):
        logger.info("Generation %d / %d", gen + 1, config.n_generations)
        evals: list[EvaluationResult] = []
        for genome in population:
            ev = evaluator.evaluate(genome, split="train")
            evals.append(ev)
            n_trials_so_far += 1

        scores = composite_fitness(
            evals,
            n_trials_so_far=n_trials_so_far,
            fee_per_bet=config.fee_per_bet,
            placebo_perms=config.placebo_perms,
            seed=config.seed + gen,
            bets_per_year=config.bets_per_year,
        )

        best_i = max(range(len(scores)), key=lambda i: scores[i].composite)
        composites = sorted(s.composite for s in scores)
        median = composites[len(composites) // 2] if composites else 0.0
        gen_records.append(GenerationRecord(
            generation=gen,
            best_genome=population[best_i].as_dict(),
            best_fitness=scores[best_i].to_dict(),
            median_composite=median,
            n_trials_so_far=n_trials_so_far,
            population=[
                {"genome": g.as_dict(), "fitness": s.to_dict()}
                for g, s in zip(population, scores, strict=True)
            ],
        ))
        logger.info(
            "  best composite=%.4f sr=%.3f dsr=%.3f pbo=%.3f p=%.3f tx=%.3f",
            scores[best_i].composite, scores[best_i].sharpe_per_bet,
            scores[best_i].dsr, scores[best_i].pbo,
            scores[best_i].placebo_p, scores[best_i].tx_robust,
        )

        if gen == config.n_generations - 1:
            break

        # Build next generation: elites + tournament-selected offspring
        elite_idx = sorted(range(len(scores)),
                           key=lambda i: scores[i].composite,
                           reverse=True)[: config.elite_count]
        elites = [population[i] for i in elite_idx]
        offspring: list[Genome] = []
        while len(elites) + len(offspring) < config.population_size:
            p1 = _tournament_pick(population, scores, config.tournament_size, rng)
            p2 = _tournament_pick(population, scores, config.tournament_size, rng)
            child = crossover(p1, p2, space, rng)
            child = child.mutate(space, rng, rate=config.mutation_rate)
            offspring.append(child)
        population = _diversify(elites + offspring, space, rng)

    # ---- hold-out evaluation of final elites ----
    final_scores = scores  # type: ignore[has-type]
    elite_idx = sorted(range(len(final_scores)),
                       key=lambda i: final_scores[i].composite,
                       reverse=True)[: config.elite_count]
    elite_genomes = [population[i] for i in elite_idx]
    elite_train_dicts: list[dict] = [
        {"genome": g.as_dict(), "fitness": final_scores[i].to_dict()}
        for g, i in zip(elite_genomes, elite_idx, strict=True)
    ]
    # Evaluate the whole elite set together so PBO has ≥2 variants to
    # compare. Evaluating elites one-at-a-time would leave PBO at its
    # default 1.0 and crush every composite to zero — a bug, not a finding.
    holdout_evals = [evaluator.evaluate(g, split="holdout") for g in elite_genomes]
    holdout_scores = composite_fitness(
        holdout_evals,
        n_trials_so_far=n_trials_so_far,        # SAME trial count — hold-out doesn't reset it
        fee_per_bet=config.fee_per_bet,
        placebo_perms=config.placebo_perms,
        seed=config.seed + 9999,
        bets_per_year=config.bets_per_year,
    )
    elite_holdout_dicts: list[dict] = [
        {"genome": g.as_dict(), "fitness": s.to_dict()}
        for g, s in zip(elite_genomes, holdout_scores, strict=True)
    ]

    finished = datetime.now(timezone.utc).isoformat()
    report = EvolutionReport(
        config=config.__dict__,
        search_space_name=space.name,
        started_utc=started,
        finished_utc=finished,
        generations=gen_records,
        elite_train=elite_train_dicts,
        elite_holdout=elite_holdout_dicts,
        n_trials_total=n_trials_so_far,
    )
    if log_path is not None:
        log_path.write_text(report.to_json())
        logger.info("evolution report written → %s", log_path)
    return report
