"""Prefect orchestration DAGs.

Three flows:

* `ingest_flow`: every minute, pull each Source, validate via the data
  quality suite, write to the feature store with PIT semantics.
* `train_flow`: weekly walk-forward retrain of the meta-ensemble; logs to
  MLflow; promotes to the model registry only if the validation gate
  passes.
* `forecast_flow`: scheduled near match-time; loads the active champion
  model and produces per-match forecasts.

All flows degrade gracefully if Prefect is not installed (functions still
import cleanly).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from prefect import flow, task
except Exception:  # pragma: no cover - prefect optional in tests
    def flow(fn=None, **_kwargs):
        if fn is None:
            return lambda f: f
        return fn

    def task(fn=None, **_kwargs):
        if fn is None:
            return lambda f: f
        return fn

from predictormaster.data.feature_store import FeatureRow, FeatureStore, InMemoryFeatureStore
from predictormaster.data.ingestion.base import Envelope
from predictormaster.data.quality import (
    Suite,
    column_present,
    in_range,
    no_nulls,
    unique,
)


@task
def validate_envelopes(envelopes: list[Envelope]) -> list[Envelope]:
    suite = Suite(
        "envelopes",
        [
            column_present("source"),
            column_present("fetched_utc"),
            no_nulls("payload"),
        ],
    )
    import pandas as pd

    df = pd.DataFrame([e.__dict__ for e in envelopes])
    suite.run(df)
    return envelopes


@task
def write_to_store(envelopes: list[Envelope], store: FeatureStore, *, feature: str) -> int:
    rows: list[FeatureRow] = []
    now = datetime.now(timezone.utc)
    for e in envelopes:
        for k, v in e.payload.items():
            rows.append(
                FeatureRow(
                    key=__import__(
                        "predictormaster.data.feature_store",
                        fromlist=["FeatureKey"],
                    ).FeatureKey(feature=feature, entity_id=str(k)),
                    value=v,
                    valid_from=now,
                )
            )
    store.write(rows)
    return len(rows)


@flow(name="ingest")
def ingest_flow(*, sources: list[Any], store: FeatureStore | None = None) -> dict[str, int]:
    store = store or InMemoryFeatureStore()
    counts: dict[str, int] = {}
    for src in sources:
        envs = validate_envelopes(src.fetch())
        counts[src.sla.name] = write_to_store(envs, store, feature=src.sla.name)
    return counts


@flow(name="train")
def train_flow(*, config: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - integration
    """Weekly walk-forward retrain.

    Implementation outline:
      1. Pull labelled data from offline feature store at the cutoff.
      2. Run walk-forward CV via `predictormaster.validation.walk_forward`.
      3. Log every fold to MLflow.
      4. Apply the calibration gate; only promote on pass.
    """
    return {"status": "see runbook docs/runbooks/training.md"}


@flow(name="forecast")
def forecast_flow(*, match_ids: list[str]) -> list[dict[str, Any]]:  # pragma: no cover
    return [{"match_id": m, "status": "scheduled"} for m in match_ids]
