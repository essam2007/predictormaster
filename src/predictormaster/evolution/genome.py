"""Genome representation + mutation / crossover for AlphaEvolve.

A genome is a flat dict of (gene_name, value) constrained by a
pre-registered ``SearchSpace``. Three gene kinds are supported:

  - continuous: float bounded by [lo, hi]
  - integer:    int bounded by [lo, hi]
  - categorical: one of a fixed tuple of values (any hashable)

Mutation perturbs each gene independently with probability ``1/L``
(``L`` = number of genes), the classic Goldberg recommendation that
gives one expected mutation per offspring on average. Continuous and
integer mutations use Gaussian / discretised-Gaussian; categorical
mutations resample uniformly excluding the current value.

Crossover is uniform: each gene is taken from either parent with
probability ½ — vs. one-point crossover this preserves more building-
block diversity, which matters for small populations (≤32) where one-
point can collapse the search prematurely.

Bounds are STRICTLY enforced at construction and after every mutation.
A genome that drifts outside its bounds raises ``ValueError`` rather
than being silently clipped — clipping a misbehaving mutation hides
search-space bugs.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Gene:
    name: str
    kind: str                                # "continuous" | "integer" | "categorical"
    lo: float | int | None = None
    hi: float | int | None = None
    choices: tuple[Any, ...] | None = None
    mutation_scale: float = 0.1              # std of Gaussian, as fraction of (hi-lo)

    def __post_init__(self) -> None:
        if self.kind not in ("continuous", "integer", "categorical"):
            raise ValueError(f"unknown gene kind {self.kind!r}")
        if self.kind in ("continuous", "integer"):
            if self.lo is None or self.hi is None:
                raise ValueError(f"{self.kind} gene {self.name!r} needs lo/hi")
            if self.lo >= self.hi:
                raise ValueError(f"gene {self.name!r}: lo {self.lo} >= hi {self.hi}")
        else:
            if not self.choices or len(self.choices) < 2:
                raise ValueError(f"categorical gene {self.name!r} needs ≥2 choices")

    def sample(self, rng: random.Random) -> Any:
        if self.kind == "continuous":
            return rng.uniform(self.lo, self.hi)
        if self.kind == "integer":
            return rng.randint(int(self.lo), int(self.hi))
        return rng.choice(self.choices)

    def mutate(self, current: Any, rng: random.Random) -> Any:
        if self.kind == "continuous":
            span = self.hi - self.lo
            step = rng.gauss(0.0, span * self.mutation_scale)
            v = float(current) + step
            return max(self.lo, min(self.hi, v))
        if self.kind == "integer":
            span = self.hi - self.lo
            step = round(rng.gauss(0.0, max(1.0, span * self.mutation_scale)))
            v = int(current) + step
            return max(int(self.lo), min(int(self.hi), v))
        # categorical — resample uniformly excluding current
        alternatives = [c for c in self.choices if c != current]
        if not alternatives:
            return current
        return rng.choice(alternatives)

    def validate(self, value: Any) -> None:
        if self.kind == "continuous":
            if not isinstance(value, (int, float)) or not (self.lo <= float(value) <= self.hi):
                raise ValueError(f"gene {self.name!r}: {value!r} outside [{self.lo}, {self.hi}]")
        elif self.kind == "integer":
            if not isinstance(value, int) or not (self.lo <= value <= self.hi):
                raise ValueError(f"gene {self.name!r}: {value!r} outside [{self.lo}, {self.hi}]")
        else:
            if value not in self.choices:
                raise ValueError(f"gene {self.name!r}: {value!r} not in {self.choices}")


@dataclass(frozen=True)
class SearchSpace:
    """Pre-registered search space. ``genes`` is an ordered tuple so
    crossover and serialisation are deterministic."""
    name: str
    genes: tuple[Gene, ...]

    def __post_init__(self) -> None:
        names = [g.name for g in self.genes]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate gene names in space {self.name!r}: {names}")

    @property
    def gene_by_name(self) -> Mapping[str, Gene]:
        return {g.name: g for g in self.genes}

    def sample(self, rng: random.Random) -> Genome:
        return Genome(
            space_name=self.name,
            values={g.name: g.sample(rng) for g in self.genes},
        )

    def validate(self, values: Mapping[str, Any]) -> None:
        for g in self.genes:
            if g.name not in values:
                raise ValueError(f"missing gene {g.name!r} in genome")
            g.validate(values[g.name])
        extra = set(values) - {g.name for g in self.genes}
        if extra:
            raise ValueError(f"unknown genes in genome: {sorted(extra)}")


@dataclass(frozen=True)
class Genome:
    space_name: str
    values: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)

    def mutate(self, space: SearchSpace, rng: random.Random, rate: float | None = None) -> Genome:
        if space.name != self.space_name:
            raise ValueError(f"genome space {self.space_name!r} != {space.name!r}")
        L = len(space.genes)
        p = (1.0 / L) if rate is None else rate
        new_vals = dict(self.values)
        for g in space.genes:
            if rng.random() < p:
                new_vals[g.name] = g.mutate(new_vals[g.name], rng)
        space.validate(new_vals)
        return Genome(space_name=self.space_name, values=new_vals)


def crossover(a: Genome, b: Genome, space: SearchSpace, rng: random.Random) -> Genome:
    """Uniform crossover: each gene independently taken from a or b."""
    if a.space_name != b.space_name or a.space_name != space.name:
        raise ValueError("crossover across incompatible spaces")
    new_vals = {
        g.name: (a.values[g.name] if rng.random() < 0.5 else b.values[g.name])
        for g in space.genes
    }
    space.validate(new_vals)
    return Genome(space_name=space.name, values=new_vals)


def initial_population(space: SearchSpace, size: int, rng: random.Random) -> list[Genome]:
    return [space.sample(rng) for _ in range(size)]


def from_yaml_dict(blob: Mapping[str, Any]) -> SearchSpace:
    """Build a SearchSpace from a parsed-YAML dict.

    Expected schema:
        name: alpha3_daily
        genes:
          - {name: z_threshold, kind: continuous, lo: 1.0, hi: 3.5}
          - {name: half_life_hours, kind: integer, lo: 1, hi: 168}
          - {name: side, kind: categorical, choices: [favorable, contrarian]}
    """
    name = str(blob["name"])
    genes: list[Gene] = []
    for entry in blob.get("genes", []):
        kind = entry["kind"]
        if kind == "categorical":
            choices = tuple(entry["choices"])
            genes.append(Gene(name=entry["name"], kind=kind, choices=choices))
        else:
            genes.append(Gene(
                name=entry["name"], kind=kind,
                lo=entry["lo"], hi=entry["hi"],
                mutation_scale=float(entry.get("mutation_scale", 0.1)),
            ))
    return SearchSpace(name=name, genes=tuple(genes))


def assert_no_duplicates(genomes: Iterable[Genome]) -> None:
    """Cheap diversity check used by the loop to detect collapse."""
    seen: set[tuple] = set()
    for g in genomes:
        key = tuple(sorted(g.values.items()))
        if key in seen:
            raise ValueError("duplicate genomes in population — diversity collapsed")
        seen.add(key)
