"""Lightweight Great-Expectations-style data quality assertions.

These are blocking on critical-tier failures and warning-only on advisory tier.
Wired into ingestion in `pipelines/prefect_flows.py`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class DataQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Expectation:
    name: str
    check: Callable[[pd.DataFrame], bool]
    severity: str = "critical"  # critical | warning
    message: str = ""

    def evaluate(self, df: pd.DataFrame) -> tuple[bool, str]:
        try:
            ok = bool(self.check(df))
        except Exception as exc:  # check itself errored → treat as failure
            return False, f"{self.name}: check raised {exc!r}"
        return ok, "" if ok else f"{self.name}: {self.message or 'failed'}"


def column_present(col: str) -> Expectation:
    return Expectation(
        name=f"column_present[{col}]",
        check=lambda df: col in df.columns,
        message=f"missing column {col}",
    )


def no_nulls(col: str) -> Expectation:
    return Expectation(
        name=f"no_nulls[{col}]",
        check=lambda df: bool(df[col].notna().all()) if col in df.columns else False,
        message=f"nulls present in {col}",
    )


def in_range(col: str, lo: float, hi: float) -> Expectation:
    def _check(df: pd.DataFrame) -> bool:
        if col not in df.columns:
            return False
        s = pd.to_numeric(df[col], errors="coerce")
        return bool(((s >= lo) & (s <= hi)).all())

    return Expectation(
        name=f"in_range[{col}]",
        check=_check,
        message=f"{col} outside [{lo}, {hi}]",
    )


def unique(cols: list[str]) -> Expectation:
    return Expectation(
        name=f"unique[{','.join(cols)}]",
        check=lambda df: not df.duplicated(subset=cols).any(),
        message=f"duplicates on {cols}",
    )


def monotonic_time(col: str) -> Expectation:
    return Expectation(
        name=f"monotonic_time[{col}]",
        check=lambda df: bool(df[col].is_monotonic_increasing),
        severity="warning",
        message=f"{col} not monotonically increasing",
    )


@dataclass
class Suite:
    name: str
    expectations: list[Expectation]

    def run(self, df: pd.DataFrame) -> dict[str, Any]:
        critical_failures: list[str] = []
        warnings: list[str] = []
        for e in self.expectations:
            ok, msg = e.evaluate(df)
            if not ok:
                (critical_failures if e.severity == "critical" else warnings).append(msg)
        if critical_failures:
            raise DataQualityError(f"{self.name}: " + "; ".join(critical_failures))
        return {"name": self.name, "rows": len(df), "warnings": warnings}


def anomaly_zscore_mask(s: pd.Series, threshold: float = 4.0) -> np.ndarray:
    """Boolean mask flagging |z| > threshold under a robust MAD estimator."""
    arr = s.to_numpy(dtype=float)
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med)) or 1e-12
    z = 0.6745 * (arr - med) / mad
    return np.abs(z) > threshold
