"""CSV replay feed for backtesting — implements the MarketFeed protocol.

Reads two CSVs (ES and NQ) of 1-minute bars and yields them interleaved in time order.
Expected columns: ``timestamp, open, high, low, close[, volume]`` where ``timestamp`` is
ISO-8601 (timezone-aware) or epoch seconds. Naive timestamps are assumed to be ET.
"""

from __future__ import annotations

import csv
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from pathlib import Path

from ..clock import ET
from ..domain.bars import Bar
from ..domain.enums import Symbol, Timeframe


def _parse_ts(raw: str) -> datetime:
    raw = raw.strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=ET)
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt


def read_csv_bars(path: str | Path, symbol: Symbol) -> list[Bar]:
    out: list[Bar] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(
                Bar(
                    symbol=symbol,
                    timeframe=Timeframe.M1,
                    ts_open=_parse_ts(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                    is_closed=True,
                )
            )
    out.sort(key=lambda b: b.ts_open)
    return out


def merge_bars(*streams: Iterable[Bar]) -> Iterator[Bar]:
    """Merge already-sorted per-symbol bar lists into one time-ordered stream."""
    combined = [b for s in streams for b in s]
    combined.sort(key=lambda b: (b.ts_open, b.symbol.value))
    return iter(combined)


class CsvReplayFeed:
    def __init__(self, es_csv: str | Path, nq_csv: str | Path) -> None:
        self.es = read_csv_bars(es_csv, Symbol.ES)
        self.nq = read_csv_bars(nq_csv, Symbol.NQ)

    def iter_bars(self) -> Iterator[Bar]:
        return merge_bars(self.es, self.nq)

    async def stream(self) -> AsyncIterator[Bar]:
        for b in self.iter_bars():
            yield b


class MemoryReplayFeed:
    """Replay from in-memory bar lists (used by tests)."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = sorted(bars, key=lambda b: (b.ts_open, b.symbol.value))

    def iter_bars(self) -> Iterator[Bar]:
        return iter(self._bars)

    async def stream(self) -> AsyncIterator[Bar]:
        for b in self._bars:
            yield b
