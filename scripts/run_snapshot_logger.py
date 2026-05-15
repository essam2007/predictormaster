"""Standalone PM book-snapshot logger with auto-discovery.

Polls Polymarket Gamma every ``--discovery-interval`` seconds for the
top-N active binary markets, feeds their token IDs to the asynchronous
snapshot logger which records every ``--snapshot-interval`` seconds to
``logs/book_snapshots/snap-YYYYMMDDTHHMM.jsonl`` (rotated hourly).

Runs forever (or until SIGTERM). The dashboard's RunnerManager can
co-launch this as a sidecar so book data accumulates whenever the bot
is running.

Why this exists
---------------
The α2 ArbReplayEvaluator needs ≥48h of book snapshots to evaluate
hyperparameter genomes against historical PM order-book state. Until
that dataset exists, evolutionary search of α2 is blocked. This logger
is what generates that dataset.

It also gives the live system a chance to detect transient
dislocations (e.g. around news events) where YES+NO briefly drops
below 1.00 even though the median-state market has none. Today's
fresh edge sample says no arbs exist; tomorrow's might.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from predictormaster.data.ingestion import sources as ingest_sources  # noqa: E402
from predictormaster.execution.book_snapshot_logger import (  # noqa: E402
    SnapshotConfig,
    run_snapshot_logger,
)


def _real_http(url: str, params: dict | None = None) -> dict:
    """Same stdlib JSON GET as the live_runner."""
    import json
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    qs = urlencode(params) if params else ""
    full = url + ("?" + qs if qs else "")
    req = Request(full, headers={"accept": "application/json",
                                  "user-agent": "predictormaster/0.1"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _discover_tokens(limit: int) -> list[str]:
    """Return token IDs (YES + NO concatenated) for the top-``limit``
    Polymarket binary markets, ordered by liquidity."""
    from scripts.live_runner import _discover_pairs
    ingest_sources.set_http(_real_http)
    pairs = _discover_pairs(limit=limit)
    tokens: list[str] = []
    for p in pairs:
        tokens.append(p.yes_token_id)
        tokens.append(p.no_token_id)
    return tokens


async def _supervise(
    snapshot_interval: float,
    discovery_interval: float,
    market_limit: int,
    output_dir: Path,
) -> None:
    """Run discovery + snapshot loop. On each discovery tick we restart
    the snapshot inner loop with a refreshed token list — markets close
    and new ones open every few hours."""
    stop = asyncio.Event()

    def _on_sig(*_a):
        print("\n[logger] shutdown signal received", flush=True)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_sig)

    total_rows = 0
    while not stop.is_set():
        try:
            tokens = await asyncio.to_thread(_discover_tokens, market_limit)
        except Exception as e:
            logging.exception("discovery failed: %s", e)
            tokens = []
        if not tokens:
            print(f"[logger] {datetime.now(timezone.utc).isoformat()}  "
                  f"discovery returned 0 tokens; sleeping {discovery_interval}s", flush=True)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=discovery_interval)
            continue
        print(f"[logger] {datetime.now(timezone.utc).isoformat()}  "
              f"recording {len(tokens)} tokens for next {discovery_interval}s", flush=True)
        cfg = SnapshotConfig(
            token_ids=tuple(tokens),
            interval_seconds=snapshot_interval,
            output_dir=output_dir,
        )
        # inner-loop stop event so we can stop snapshots on discovery refresh
        inner_stop = asyncio.Event()
        snapshot_task = asyncio.create_task(run_snapshot_logger(cfg, inner_stop))

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=discovery_interval)
        inner_stop.set()
        try:
            written = await snapshot_task
            total_rows += written
            print(f"[logger] cycle wrote {written} rows  (total {total_rows})", flush=True)
        except Exception as e:
            logging.exception("snapshot loop crashed: %s", e)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Polymarket book-snapshot logger")
    p.add_argument("--snapshot-interval", type=float, default=5.0,
                   help="seconds between book snapshots (default 5)")
    p.add_argument("--discovery-interval", type=float, default=900.0,
                   help="seconds between Gamma re-discovery (default 900 = 15 min)")
    p.add_argument("--market-limit", type=int, default=80,
                   help="top-N markets by liquidity to record (default 80)")
    p.add_argument("--output-dir", type=Path, default=Path("logs/book_snapshots"))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[logger] writing to {args.output_dir}", flush=True)
    print(f"[logger] snapshot every {args.snapshot_interval}s, "
          f"discovery every {args.discovery_interval}s, limit={args.market_limit}",
          flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_supervise(
            snapshot_interval=args.snapshot_interval,
            discovery_interval=args.discovery_interval,
            market_limit=args.market_limit,
            output_dir=args.output_dir,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
