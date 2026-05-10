"""Elo with multiplicative margin-of-victory and home-court correction.

Update rule:

    R_a' = R_a + K * G(MOV) * (S_a - E_a)
    E_a  = 1 / (1 + 10^((R_b - R_a + h) / s))

where h is the home advantage in rating points and s is the logistic scale
(400 in classical Elo). The MOV multiplier follows Silver's
G(d) = ln(|d| + 1) * 2.2 / (0.001 * |R_a - R_b| + 2.2).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class EloRater:
    k: float = 20.0
    scale: float = 400.0
    home_advantage: float = 60.0
    initial_rating: float = 1500.0
    ratings: dict[str, float] = field(default_factory=dict)

    def get(self, team: str) -> float:
        return self.ratings.get(team, self.initial_rating)

    def expected(self, home: str, away: str) -> float:
        diff = (self.get(away) - self.get(home) - self.home_advantage) / self.scale
        return 1.0 / (1.0 + 10.0 ** diff)

    def _mov_multiplier(self, score_diff: float, rating_diff: float) -> float:
        import math

        margin = abs(score_diff)
        if margin == 0:
            return 1.0
        return math.log(margin + 1.0) * 2.2 / (0.001 * abs(rating_diff) + 2.2)

    def update(
        self,
        *,
        home: str,
        away: str,
        home_score: float,
        away_score: float,
    ) -> tuple[float, float]:
        e_home = self.expected(home, away)
        s_home = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
        rating_diff = self.get(home) + self.home_advantage - self.get(away)
        mov = self._mov_multiplier(home_score - away_score, rating_diff)
        delta = self.k * mov * (s_home - e_home)
        self.ratings[home] = self.get(home) + delta
        self.ratings[away] = self.get(away) - delta
        return self.ratings[home], self.ratings[away]


@dataclass
class EloLeague:
    """Convenience wrapper that batches updates and exposes a leaderboard."""

    rater: EloRater = field(default_factory=EloRater)
    games: int = 0
    per_team_games: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def ingest(self, matches: list[dict]) -> None:
        for m in matches:
            self.rater.update(
                home=m["home"],
                away=m["away"],
                home_score=m["home_score"],
                away_score=m["away_score"],
            )
            self.games += 1
            self.per_team_games[m["home"]] += 1
            self.per_team_games[m["away"]] += 1

    def leaderboard(self) -> list[tuple[str, float, int]]:
        return sorted(
            ((t, r, self.per_team_games[t]) for t, r in self.rater.ratings.items()),
            key=lambda x: x[1],
            reverse=True,
        )
