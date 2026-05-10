"""Pydantic record schemas for every data class crossing a system boundary.

These are the only types allowed in feature store ingestion and inference
contracts. Versioned via the `schema_version` discriminator field.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Sport(str, Enum):
    BASKETBALL = "basketball"
    SOCCER = "soccer"
    BASEBALL = "baseball"
    AMERICAN_FOOTBALL = "american_football"
    MMA = "mma"
    TENNIS = "tennis"
    F1 = "f1"
    ESPORTS = "esports"
    CRICKET = "cricket"
    HOCKEY = "hockey"


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1


class Match(_Base):
    match_id: str
    sport: Sport
    home_id: str
    away_id: str
    kickoff_utc: datetime
    venue_id: str | None = None
    season: str
    competition: str

    @field_validator("kickoff_utc")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("kickoff_utc must be timezone-aware (UTC)")
        return v


class MatchResult(_Base):
    match_id: str
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    finished_utc: datetime
    extra_time: bool = False


class PlayerStat(_Base):
    match_id: str
    player_id: str
    team_id: str
    minutes: float = Field(ge=0)
    features: dict[str, float]


class InjuryReport(_Base):
    player_id: str
    team_id: str
    reported_utc: datetime
    status: Literal["out", "doubtful", "questionable", "probable", "available"]
    expected_return_utc: datetime | None = None


class Sentiment(_Base):
    """One emitted record from the NLP pipeline."""

    entity_id: str
    entity_kind: Literal["player", "team", "match", "competition"]
    observed_utc: datetime
    polarity: float = Field(ge=-1.0, le=1.0)
    intensity: float = Field(ge=0.0, le=1.0)
    labels: dict[str, float]
    source: str


class ConsensusSnapshot(_Base):
    """Aggregated public-consensus probability snapshot."""

    match_id: str
    observed_utc: datetime
    p_home: float
    p_draw: float
    p_away: float
    n_sources: int = Field(ge=1)

    @field_validator("p_home", "p_draw", "p_away")
    @classmethod
    def _prob(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("probabilities must lie in [0, 1]")
        return v


class WeatherObservation(_Base):
    venue_id: str
    observed_utc: datetime
    temperature_c: float
    wind_kph: float
    precipitation_mm: float
    humidity: float = Field(ge=0.0, le=1.0)


class Forecast(_Base):
    """The contract for any served forecast."""

    match_id: str
    model_id: str
    produced_utc: datetime
    p_home: float
    p_draw: float
    p_away: float
    expected_score_home: float
    expected_score_away: float
    score_pmf: dict[str, float] | None = None
    epistemic_var: float
    aleatoric_var: float
    credible_interval_90: tuple[float, float]
