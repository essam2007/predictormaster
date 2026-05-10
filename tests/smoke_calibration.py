"""Calibration smoke check used by the CI calibration-gate job.

Trains nothing — generates synthetic well-calibrated forecasts, asserts
that the report passes the same gate the production pipeline applies.
"""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile

import numpy as np

from predictormaster.validation.report import passes_gate, render_report


def main() -> int:
    rng = np.random.default_rng(42)
    n = 5000
    p = rng.uniform(0.2, 0.8, size=n)
    y = rng.binomial(1, p)
    climatology = np.full(n, y.mean())
    with tempfile.TemporaryDirectory() as tmp:
        manifest = render_report(
            probs=p,
            labels=y,
            climatology_probs=climatology,
            market_probs=None,
            out_dir=Path(tmp),
            model_id="smoke",
            git_sha="local",
            data_version="synthetic",
        )
        ok, failures = passes_gate(manifest)
        if not ok:
            print("calibration gate failed:", failures, file=sys.stderr)
            return 1
        print(f"smoke ok: ECE={manifest.ece:.4f} BSS={manifest.bss_vs_climatology:.4f}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
