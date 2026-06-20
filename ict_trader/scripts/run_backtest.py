#!/usr/bin/env python
"""Thin wrapper around the backtest CLI: python scripts/run_backtest.py --csv-es ... --csv-nq ..."""

from __future__ import annotations

from ict_trader.backtest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
