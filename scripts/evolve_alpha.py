"""Operator entry point for one AlphaEvolve iteration.

Usage
-----
    python scripts/evolve_alpha.py --alpha alpha3_daily \\
        --start 2023-08-01 --end 2025-05-31 \\
        --generations 4 --pop 20 --seed 7

    python scripts/evolve_alpha.py --alpha alpha2_intra_poly \\
        --snapshot-dir logs/book_snapshots

Outputs
-------
    scripts/evolve_results/alpha3_daily-YYYYmmddTHHMM.json
    scripts/evolve_results/alpha2_intra_poly-YYYYmmddTHHMM.json

Reads ``configs/evolve_search_spaces.yaml`` as the pre-registered
search space — editing that file is treated as a new experiment.

This script DOES NOT run in --mode live; it never places orders. All
evaluations are against cached real data (GDELT + EPL closing odds)
or recorded snapshot logs (PM books).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predictormaster.evolution import EvolutionConfig, evolve  # noqa: E402
from predictormaster.evolution.evaluators import (  # noqa: E402
    ArbReplayEvaluator,
    build_sentiment_daily_evaluator,
)
from predictormaster.evolution.genome import from_yaml_dict  # noqa: E402


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _load_space(name: str, path: Path):
    blob = yaml.safe_load(path.read_text())
    if name not in blob:
        raise SystemExit(f"unknown alpha {name!r}; available: {sorted(blob)}")
    return from_yaml_dict(blob[name])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", required=True,
                    choices=["alpha3_daily", "alpha2_intra_poly"])
    ap.add_argument("--start", type=_parse_date, default=date(2023, 8, 1))
    ap.add_argument("--end", type=_parse_date, default=date(2025, 5, 31))
    ap.add_argument("--snapshot-dir", type=Path, default=Path("logs/book_snapshots"))
    ap.add_argument("--generations", type=int, default=4)
    ap.add_argument("--pop", type=int, default=20)
    ap.add_argument("--elites", type=int, default=4)
    ap.add_argument("--placebo-perms", type=int, default=400)
    ap.add_argument("--fee", type=float, default=0.02,
                    help="fee per bet in stake units for tx-robustness term")
    ap.add_argument("--bets-per-year", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--config", type=Path,
                    default=Path("configs/evolve_search_spaces.yaml"))
    ap.add_argument("--output-dir", type=Path,
                    default=Path("scripts/evolve_results"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    space = _load_space(args.alpha, args.config)

    if args.alpha == "alpha3_daily":
        print(f"[evolve] building α3-daily evaluator from EPL {args.start}..{args.end}")
        print("[evolve] WARNING: this is a daily-frequency proxy for α3 — real α3 needs")
        print("[evolve]          intra-day book data which we do not yet have.")
        evaluator = build_sentiment_daily_evaluator(args.start, args.end)
        n_train = (evaluator.matches["date"] < evaluator.train_cutoff).sum()
        n_hold = len(evaluator.matches) - n_train
        teams_with_tone = sum(1 for s in evaluator.tone_by_team.values() if not s.empty)
        print(f"[evolve] matches: {n_train} train / {n_hold} holdout")
        print(f"[evolve] GDELT coverage: {teams_with_tone}/{len(evaluator.tone_by_team)} teams")
    else:
        print(f"[evolve] building α2 arb-replay evaluator from {args.snapshot_dir}")
        # For α2 we need a list of OutcomePair instances; in the real
        # pipeline these come from the live PM Gamma discovery. For now
        # we accept "no pairs given" → empty result (zero fitness).
        evaluator = ArbReplayEvaluator(snapshot_dir=args.snapshot_dir, pairs=[])
        if evaluator._panel is None or evaluator._panel.empty:
            print("[evolve] no snapshots present — α2 evolution will record zero fitness")
            print("[evolve] start the snapshot logger to begin collecting data, then re-run")

    cfg = EvolutionConfig(
        population_size=args.pop,
        n_generations=args.generations,
        elite_count=args.elites,
        placebo_perms=args.placebo_perms,
        fee_per_bet=args.fee,
        bets_per_year=args.bets_per_year,
        seed=args.seed,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    out_path = args.output_dir / f"{args.alpha}-{stamp}.json"

    print(f"[evolve] running {args.generations} generations × {args.pop} population "
          f"= {args.generations * args.pop} fitness evaluations")
    print("[evolve] composite fitness = σ(sr/2) × DSR × (1-PBO) × placebo × tx-robust")
    report = evolve(space, evaluator, config=cfg, log_path=out_path)

    print("\n=== ELITE GENOMES — TRAIN-FOLD FITNESS ===")
    for i, e in enumerate(report.elite_train, 1):
        f = e["fitness"]
        print(f"  #{i}: composite={f['composite']:.4f}  sr={f['sharpe_per_bet']:+.3f}  "
              f"DSR={f['dsr']:.3f}  PBO={f['pbo']:.3f}  placebo_p={f['placebo_p']:.3f}  "
              f"tx_robust={f['tx_robust']:.3f}  n_bets={f['n_bets']}")
        print(f"      genome: {json.dumps(e['genome'], default=str)}")

    print("\n=== SAME GENOMES — HOLD-OUT FITNESS ===")
    print("  (hold-out keeps the train-fold n_trials counter so the DSR bar is unchanged)")
    for i, (tr, ho) in enumerate(zip(report.elite_train, report.elite_holdout, strict=True), 1):
        ftr = tr["fitness"]
        fho = ho["fitness"]
        print(f"  #{i}: train composite={ftr['composite']:.4f}  →  "
              f"holdout composite={fho['composite']:.4f}  "
              f"(sr train→hold: {ftr['sharpe_per_bet']:+.3f} → {fho['sharpe_per_bet']:+.3f}, "
              f"n_bets {ftr['n_bets']} → {fho['n_bets']})")

    print(f"\n[evolve] report written → {out_path}")
    print("[evolve] reminder: train→holdout fitness collapse is the strongest")
    print("[evolve]           overfit signal we have; treat any large gap as a failure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
