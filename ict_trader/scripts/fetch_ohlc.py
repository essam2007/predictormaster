#!/usr/bin/env python
"""Fetch real OHLC for NQ / ES / YM from Yahoo Finance into CSVs the deck/journal can use.

Reliable, free, no API key. Writes data/<SYM>_<interval>.csv with columns
timestamp(ISO-UTC),open,high,low,close,volume. Re-run any time:

    python scripts/fetch_ohlc.py                 # default symbols + timeframes
    python scripts/fetch_ohlc.py --interval 5m --range 5d
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Yahoo continuous-front-month futures symbols.
SYMBOLS = {"NQ": "NQ=F", "ES": "ES=F", "YM": "YM=F"}
# (interval, range) pairs: 5m/15m for entries, 1h for HTF context.
TIMEFRAMES = [("5m", "5d"), ("15m", "5d"), ("60m", "1mo")]
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


def fetch(yahoo_symbol: str, interval: str, range_: str) -> list[dict]:
    url = f"{_BASE}{yahoo_symbol}?interval={interval}&range={range_}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    result = payload["chart"]["result"][0]
    stamps = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows: list[dict] = []
    for i, ts in enumerate(stamps):
        o, h, low, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, low, c):
            continue  # Yahoo leaves gaps as nulls — skip them
        rows.append({
            "timestamp": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
            "open": round(o, 2), "high": round(h, 2), "low": round(low, 2),
            "close": round(c, 2), "volume": int(q["volume"][i] or 0),
        })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--interval", help="fetch a single interval instead of the defaults")
    ap.add_argument("--range", dest="range_", default="5d")
    args = ap.parse_args()

    out = Path(args.out)
    tfs = [(args.interval, args.range_)] if args.interval else TIMEFRAMES
    for name, ysym in SYMBOLS.items():
        for interval, range_ in tfs:
            try:
                rows = fetch(ysym, interval, range_)
            except Exception as exc:  # noqa: BLE001 - report and continue to next file
                print(f"  {name} {interval:>4}: FAILED ({type(exc).__name__}: {exc})")
                continue
            path = out / f"{name}_{interval}.csv"
            write_csv(rows, path)
            span = f"{rows[0]['timestamp'][:16]} … {rows[-1]['timestamp'][:16]}" if rows else "empty"
            print(f"  {name} {interval:>4}: {len(rows):5d} bars  [{span}]  -> {path}")
            time.sleep(0.4)  # be polite to the endpoint


if __name__ == "__main__":
    main()
