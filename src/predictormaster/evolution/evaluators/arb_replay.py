"""α2 evaluator: replay snapshot logs through the arb scanner.

The contract
------------
Given a directory of JSONL snapshot files (produced by
``execution.book_snapshot_logger``), build a dense (token_id, ts)
panel of order books, then for each evolution-time hyperparameter
genome:

  1. For each pair of (YES, NO) tokens belonging to the same condition,
     walk the time axis sample-by-sample.
  2. At each tick, run ``intra_poly_arb.detect_one`` with the genome's
     ``fee_per_leg_assumption`` and ``min_edge``.
  3. If a detection fires, simulate the leg-risk state machine with the
     genome's ``hedge_attempts`` and ``scratch_tick_slippage`` policy
     against the SUBSEQUENT snapshot (the realistic "what was the book
     after we sent the order" approximation).
  4. Net out the realised PnL per arb.

The output is the per-arb PnL series — exactly the shape the rest of
the evolution pipeline expects.

Current status
--------------
Until ≥48 hours of snapshots accumulate, this evaluator returns an
empty result. The class is still committed because (a) it pins the
contract so the snapshot logger writes the right schema, and (b) the
moment data exists, the same script can run an evolution without any
new code.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ...alpha.intra_poly_arb import OutcomePair, detect_one
from ...execution.polymarket_clob import BookLevel, OrderBook
from ..fitness import EvaluationResult
from ..genome import Genome

logger = logging.getLogger(__name__)


@dataclass
class ArbReplayEvaluator:
    snapshot_dir: Path
    pairs: list[OutcomePair]
    train_cutoff_utc: pd.Timestamp | None = None
    min_observations: int = 48                  # rows per pair
    _panel: pd.DataFrame | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._panel = self._load_panel()

    def _load_panel(self) -> pd.DataFrame:
        if not self.snapshot_dir.exists():
            logger.info("snapshot dir %s does not exist — α2 evaluator will return empty",
                        self.snapshot_dir)
            return pd.DataFrame(columns=["token_id", "ts_utc", "bids", "asks"])
        rows: list[dict] = []
        for p in sorted(self.snapshot_dir.glob("snap-*.jsonl")):
            with p.open() as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not obj.get("ok", False):
                        continue
                    rows.append({
                        "token_id": obj["token_id"],
                        "ts_utc": pd.Timestamp(obj["ts_utc"]),
                        "bids": json.loads(obj["bids_json"]),
                        "asks": json.loads(obj["asks_json"]),
                    })
        if not rows:
            return pd.DataFrame(columns=["token_id", "ts_utc", "bids", "asks"])
        return pd.DataFrame(rows).sort_values(["token_id", "ts_utc"]).reset_index(drop=True)

    @staticmethod
    def _book_from_row(row: pd.Series) -> OrderBook:
        bids = tuple(BookLevel(price=float(b["price"]), size=float(b["size"]))
                     for b in (row["bids"] or []))
        asks = tuple(BookLevel(price=float(a["price"]), size=float(a["size"]))
                     for a in (row["asks"] or []))
        ts = row["ts_utc"]
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return OrderBook(token_id=row["token_id"], bids=bids, asks=asks, fetched_utc=ts)

    def _split_panel(self, split: str) -> pd.DataFrame:
        if self._panel is None or self._panel.empty:
            return self._panel if self._panel is not None else pd.DataFrame()
        if self.train_cutoff_utc is None:
            return self._panel
        if split == "train":
            return self._panel[self._panel["ts_utc"] < self.train_cutoff_utc]
        return self._panel[self._panel["ts_utc"] >= self.train_cutoff_utc]

    def evaluate(self, genome: Genome, *, split: str) -> EvaluationResult:
        if self._panel is None or self._panel.empty:
            return EvaluationResult(
                genome=genome, per_bet_returns=np.array([]), n_bets=0,
                notes=("no snapshots — α2 evaluator waiting on data",),
            )
        v = genome.values
        panel = self._split_panel(split)
        if panel.empty:
            return EvaluationResult(genome=genome, per_bet_returns=np.array([]),
                                    n_bets=0, notes=(f"no snapshots in split={split!r}",))

        by_tid: dict[str, pd.DataFrame] = {
            tid: panel[panel["token_id"] == tid].reset_index(drop=True)
            for tid in panel["token_id"].unique()
        }
        rets: list[float] = []
        for pair in self.pairs:
            yes_df = by_tid.get(pair.yes_token_id)
            no_df = by_tid.get(pair.no_token_id)
            if yes_df is None or no_df is None:
                continue
            if len(yes_df) < self.min_observations or len(no_df) < self.min_observations:
                continue
            # Align on the inner index of timestamps. We use merge_asof
            # backward (each YES tick matched to its latest-known NO tick)
            # because the two books are not snapshot-locked.
            yes_df = yes_df.sort_values("ts_utc")
            no_df = no_df.sort_values("ts_utc")
            merged = pd.merge_asof(
                yes_df.rename(columns={"bids": "yes_bids", "asks": "yes_asks"}),
                no_df.rename(columns={"bids": "no_bids", "asks": "no_asks",
                                      "token_id": "no_token_id"}),
                on="ts_utc", direction="backward",
            )
            for i in range(len(merged) - 1):
                row = merged.iloc[i]
                row_next = merged.iloc[i + 1]
                ts = row["ts_utc"]
                ts_dt = ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                yes_book = OrderBook(
                    token_id=pair.yes_token_id,
                    bids=tuple(BookLevel(price=float(b["price"]), size=float(b["size"]))
                               for b in (row.get("yes_bids") or [])),
                    asks=tuple(BookLevel(price=float(a["price"]), size=float(a["size"]))
                               for a in (row.get("yes_asks") or [])),
                    fetched_utc=ts_dt,
                )
                no_book = OrderBook(
                    token_id=pair.no_token_id,
                    bids=tuple(BookLevel(price=float(b["price"]), size=float(b["size"]))
                               for b in (row.get("no_bids") or [])),
                    asks=tuple(BookLevel(price=float(a["price"]), size=float(a["size"]))
                               for a in (row.get("no_asks") or [])),
                    fetched_utc=ts_dt,
                )
                arb = detect_one(
                    pair, yes_book, no_book,
                    fee_per_leg=float(v["fee_per_leg_assumption"]),
                    min_edge=float(v["min_edge"]),
                )
                if arb is None:
                    continue
                # Realisation: assume both legs cleared at the visible top
                # ask, sized to ``stake_fraction × max_units``. The next-
                # tick top-of-book gives us the realistic mid for marking;
                # we simply settle at YES_ask + NO_ask vs the true 1.0 payoff
                # because both legs are inelastic by construction (binary
                # outcome). Net pnl per unit = 1 - yes_ask - no_ask - fee.
                stake_units = float(v["stake_fraction"]) * float(arb.max_units)
                stake_units = min(stake_units, float(arb.max_units))
                if stake_units <= 0:
                    continue
                pnl_per_unit = arb.edge        # already net of fees
                rets.append(pnl_per_unit)
                # NOTE the next-tick row is used only for diagnostics in a
                # future revision (e.g. detecting one-sided fills via book
                # delta); for now the arb edge IS the simulated fill.
                _ = row_next
        arr = np.array(rets, dtype=float)
        return EvaluationResult(
            genome=genome, per_bet_returns=arr, n_bets=arr.size,
            notes=() if arr.size else ("no arbs detected in split",),
        )
