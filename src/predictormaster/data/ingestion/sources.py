"""Concrete ingestion adapters.

Network is hidden behind `_get_json`, which is monkey-patched in tests. Real
deployment wires it to httpx.AsyncClient. Each adapter declares its SLA and
maps remote shapes to internal pydantic schemas.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import SLA, Envelope, Source

_HTTP: Callable[[str, dict | None], dict] | None = None


def set_http(fn: Callable[[str, dict | None], dict]) -> None:
    global _HTTP
    _HTTP = fn


def _get_json(url: str, params: dict | None = None) -> dict:
    if _HTTP is None:
        raise RuntimeError("HTTP transport not configured; call set_http() first")
    return _HTTP(url, params)


class ResultsFeed(Source):
    sla = SLA(
        name="match_results",
        refresh=timedelta(minutes=1),
        latency_budget=timedelta(seconds=30),
    )

    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]:
        params = {"since": (asof or self.now() - timedelta(hours=1)).isoformat()}
        body = _get_json(f"{self.base_url}/results", params)
        return [Envelope(source="results", fetched_utc=self.now(), payload=p) for p in body["items"]]


class InjuryFeed(Source):
    sla = SLA(
        name="injury_reports",
        refresh=timedelta(seconds=30),
        latency_budget=timedelta(seconds=60),
    )

    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]:
        body = _get_json(f"{self.base_url}/injuries", None)
        return [Envelope(source="injuries", fetched_utc=self.now(), payload=p) for p in body["items"]]


class WeatherFeed(Source):
    sla = SLA(
        name="weather",
        refresh=timedelta(minutes=10),
        latency_budget=timedelta(seconds=15),
    )

    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]:
        body = _get_json(f"{self.base_url}/observations", None)
        return [Envelope(source="weather", fetched_utc=self.now(), payload=p) for p in body["items"]]


class ConsensusFeed(Source):
    sla = SLA(
        name="public_consensus",
        refresh=timedelta(seconds=15),
        latency_budget=timedelta(seconds=20),
    )

    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]:
        body = _get_json(f"{self.base_url}/consensus", None)
        return [Envelope(source="consensus", fetched_utc=self.now(), payload=p) for p in body["items"]]


class SocialFirehose(Source):
    """Twitter/X + Reddit adapter, normalised to a common envelope.

    Throughput target: 5k posts/sec sustained, 25k peak. In tests the firehose
    is replaced by a deterministic generator.
    """

    sla = SLA(
        name="social_firehose",
        refresh=timedelta(seconds=1),
        latency_budget=timedelta(milliseconds=500),
    )

    def __init__(self, source_name: str, generator: Callable[[], list[dict[str, Any]]]):
        self.source_name = source_name
        self._gen = generator

    def fetch(self, *, asof: datetime | None = None) -> list[Envelope]:
        return [
            Envelope(source=self.source_name, fetched_utc=self.now(), payload=p)
            for p in self._gen()
        ]


def slas() -> list[SLA]:
    return [
        ResultsFeed.sla,
        InjuryFeed.sla,
        WeatherFeed.sla,
        ConsensusFeed.sla,
        SocialFirehose.sla,
    ]
