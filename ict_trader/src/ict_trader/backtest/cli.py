"""CLI: run a backtest from two CSVs and print per-bucket analytics as JSON."""

from __future__ import annotations

import argparse
import json
import sys

from ..analytics.calibration import component_lift, score_reliability
from ..analytics.metrics import equity_curve, summarize
from ..domain.enums import Symbol
from ..marketdata.replay import CsvReplayFeed
from .harness import Backtester


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ICT auto-trader backtest")
    p.add_argument("--csv-es", required=True, help="ES 1-minute CSV")
    p.add_argument("--csv-nq", required=True, help="NQ 1-minute CSV")
    p.add_argument("--traded", default="NQ", choices=[s.value for s in Symbol])
    p.add_argument("--slippage", type=float, default=0.25)
    p.add_argument("--out", default="-", help="output JSON path or - for stdout")
    args = p.parse_args(argv)

    feed = CsvReplayFeed(args.csv_es, args.csv_nq)
    bt = Backtester(feed, traded=Symbol(args.traded), slippage_points=args.slippage)
    res = bt.run()

    report = {
        "n_setups": len(res.setups),
        "n_signals": res.n_signals,
        "n_trades": res.n_trades,
        "summary": summarize(res.trades),
        "equity_curve": equity_curve(res.trades),
        "component_lift": component_lift(res.trades, res.setups),
        "score_reliability": score_reliability(res.trades),
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
