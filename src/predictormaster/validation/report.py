"""Single-script reproducible calibration / validation report renderer.

Outputs a JSON manifest plus an optional matplotlib reliability diagram. CI
parses the JSON to apply gating thresholds before model promotion.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .calibration import (
    CalibrationReport,
    brier_skill_score,
    expected_calibration_error,
    log_loss,
)


@dataclass
class ValidationManifest:
    model_id: str
    git_sha: str
    data_version: str
    produced_utc: str
    n_predictions: int
    log_loss: float
    brier: float
    bss_vs_climatology: float
    bss_vs_market: float | None
    ece: float
    mce: float
    reliability: float
    resolution: float
    uncertainty: float
    notes: str = ""


def render_report(
    *,
    probs: np.ndarray,
    labels: np.ndarray,
    climatology_probs: np.ndarray,
    market_probs: np.ndarray | None,
    out_dir: Path,
    model_id: str,
    git_sha: str,
    data_version: str,
    notes: str = "",
) -> ValidationManifest:
    out_dir.mkdir(parents=True, exist_ok=True)
    cal = expected_calibration_error(probs, labels, n_bins=15)
    manifest = ValidationManifest(
        model_id=model_id,
        git_sha=git_sha,
        data_version=data_version,
        produced_utc=datetime.now(timezone.utc).isoformat(),
        n_predictions=len(probs),
        log_loss=log_loss(probs, labels),
        brier=cal.brier,
        bss_vs_climatology=brier_skill_score(probs, labels, climatology_probs),
        bss_vs_market=(brier_skill_score(probs, labels, market_probs) if market_probs is not None else None),
        ece=cal.ece,
        mce=cal.mce,
        reliability=cal.reliability,
        resolution=cal.resolution,
        uncertainty=cal.uncertainty,
        notes=notes,
    )
    (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2))
    np.savez(
        out_dir / "reliability.npz",
        bin_centers=cal.bin_centers,
        bin_confidences=cal.bin_confidences,
        bin_accuracies=cal.bin_accuracies,
        bin_counts=cal.bin_counts,
    )
    return manifest


def gate_thresholds() -> dict[str, float]:
    """Promotion thresholds enforced in CI."""
    return {"ece_max": 0.05, "bss_climatology_min": 0.05}


def passes_gate(manifest: ValidationManifest) -> tuple[bool, list[str]]:
    th = gate_thresholds()
    failures: list[str] = []
    if manifest.ece > th["ece_max"]:
        failures.append(f"ECE {manifest.ece:.4f} > {th['ece_max']}")
    if manifest.bss_vs_climatology < th["bss_climatology_min"]:
        failures.append(
            f"BSS_climatology {manifest.bss_vs_climatology:.4f} < {th['bss_climatology_min']}"
        )
    return not failures, failures


def _probs_for_label(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    if probs.ndim == 1:
        return probs
    n = probs.shape[0]
    return probs[np.arange(n), labels]
