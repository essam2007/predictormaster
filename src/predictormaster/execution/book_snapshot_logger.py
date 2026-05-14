"""Asynchronous Polymarket order-book snapshot logger.

Writes raw (token_id, ts_utc, bids, asks) rows to a Parquet file
sharded by hour. Designed to run in the background of ``live_runner``
or as a standalone process — minutes of wall-clock per snapshot batch
is fine; we are recording for *later* evolutionary analysis, not for
live decisions.

Why Parquet
-----------
Columnar storage compresses dense order-book payloads well (typically
8-12x vs raw JSON for PM books with ≤32 levels). Time-series readers
(pyarrow, duckdb) can pushdown filter on (token_id, ts) without
parsing every row.

What it does NOT do
-------------------
  - No L3 (per-order) reconstruction. PM REST only exposes aggregated
    L2 levels; the logger preserves what the API gives us.
  - No retry storms. On HTTP failure it logs and continues. Snapshot
    gaps are acceptable for evolutionary backtests; they are NOT
    acceptable for live execution decisions, which use a separate
    real-time book fetch.
  - No order-by-order replay. To get tick-level granularity you would
    need PM's WebSocket book feed and a separate logger.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CLOB_BOOK_URL = "https://clob.polymarket.com/book"


@dataclass(frozen=True)
class SnapshotConfig:
    token_ids: tuple[str, ...]
    interval_seconds: float = 5.0
    output_dir: Path = Path("logs/book_snapshots")
    rotation_minutes: int = 60
    http_timeout: float = 4.0
    max_concurrent_fetches: int = 8


async def _fetch_one(client: httpx.AsyncClient, token_id: str, timeout: float) -> dict | None:
    try:
        r = await client.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=timeout)
        if r.status_code != 200:
            logger.debug("book HTTP %d for %s", r.status_code, token_id)
            return None
        return r.json()
    except (httpx.HTTPError, asyncio.TimeoutError, json.JSONDecodeError) as e:
        logger.debug("book fetch failed for %s: %s", token_id, e)
        return None


async def _gather_books(
    client: httpx.AsyncClient,
    token_ids: Iterable[str],
    timeout: float,
    max_concurrent: int,
) -> dict[str, dict | None]:
    sem = asyncio.Semaphore(max_concurrent)

    async def bounded(tid: str) -> tuple[str, dict | None]:
        async with sem:
            return tid, await _fetch_one(client, tid, timeout)

    results = await asyncio.gather(*(bounded(t) for t in token_ids))
    return dict(results)


def _serialise_row(token_id: str, ts: datetime, payload: dict | None) -> dict:
    if payload is None or not isinstance(payload, dict):
        return {"token_id": token_id, "ts_utc": ts.isoformat(),
                "bids_json": "[]", "asks_json": "[]", "ok": False}
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    return {
        "token_id": token_id,
        "ts_utc": ts.isoformat(),
        "bids_json": json.dumps(bids, separators=(",", ":")),
        "asks_json": json.dumps(asks, separators=(",", ":")),
        "ok": True,
    }


def _shard_path(output_dir: Path, ts: datetime, rotation_minutes: int) -> Path:
    bucket = ts.replace(
        minute=(ts.minute // rotation_minutes) * rotation_minutes,
        second=0, microsecond=0,
    )
    return output_dir / f"snap-{bucket.strftime('%Y%m%dT%H%M')}.jsonl"


async def run_snapshot_logger(cfg: SnapshotConfig, stop_event: asyncio.Event) -> int:
    """Run until ``stop_event.set()`` is called. Returns total rows written.

    Each row is one JSON object per line (jsonl). We deliberately use
    JSONL not Parquet at this layer because the writer must be append-
    only across process restarts; Parquet is a *batch* format and
    would require a separate compaction job. The reader-side code in
    ``evaluators/arb_replay.py`` will convert JSONL → in-memory frame
    on the fly, and a periodic compactor can be added later.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    headers = {"accept": "application/json"}
    async with httpx.AsyncClient(headers=headers, http2=True, timeout=cfg.http_timeout) as client:
        while not stop_event.is_set():
            t0 = time.perf_counter()
            ts = datetime.now(timezone.utc)
            books = await _gather_books(
                client, cfg.token_ids, cfg.http_timeout, cfg.max_concurrent_fetches
            )
            path = _shard_path(cfg.output_dir, ts, cfg.rotation_minutes)
            with path.open("a") as f:
                for tid, payload in books.items():
                    row = _serialise_row(tid, ts, payload)
                    f.write(json.dumps(row) + "\n")
                    total += 1
            elapsed = time.perf_counter() - t0
            wait = max(0.0, cfg.interval_seconds - elapsed)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=wait)
    return total
