#!/usr/bin/env python
"""Validate / inspect historical 1-minute CSVs before backtesting.

In production this also pulls history from the configured feed (DataBento recommended) into
the store. Without a data subscription it simply validates the CSVs the replay engine will
consume and reports coverage, so you can confirm your ES/NQ files line up before a backtest.

Usage: python scripts/seed_history.py --csv-es es.csv --csv-nq nq.csv
"""

from __future__ import annotations

import argparse

from ict_trader.domain.enums import Symbol
from ict_trader.marketdata.replay import read_csv_bars


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv-es", required=True)
    p.add_argument("--csv-nq", required=True)
    args = p.parse_args()
    es = read_csv_bars(args.csv_es, Symbol.ES)
    nq = read_csv_bars(args.csv_nq, Symbol.NQ)
    print(f"ES: {len(es)} bars  {es[0].ts_open} -> {es[-1].ts_open}")
    print(f"NQ: {len(nq)} bars  {nq[0].ts_open} -> {nq[-1].ts_open}")
    es_ts = {b.ts_open for b in es}
    nq_ts = {b.ts_open for b in nq}
    common = es_ts & nq_ts
    print(f"aligned minutes: {len(common)}  "
          f"(ES-only {len(es_ts - nq_ts)}, NQ-only {len(nq_ts - es_ts)})")


if __name__ == "__main__":
    main()
