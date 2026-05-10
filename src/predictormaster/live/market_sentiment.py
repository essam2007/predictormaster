"""Market-implied sentiment features per game."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .registry import LiveGame


@dataclass(frozen=True)
class MarketFeatures:
    consensus_home: float
    consensus_away: float
    dispersion: float
    venues_n: int
    skew: float


def features(g: LiveGame) -> MarketFeatures:
    hs = [v.implied_home for v in g.venues.values() if v.implied_home > 0]
    aws = [v.implied_away for v in g.venues.values() if v.implied_away > 0]
    if not hs or not aws:
        return MarketFeatures(0.0, 0.0, 0.0, 0, 0.0)
    h = float(np.mean(hs))
    a = float(np.mean(aws))
    disp = float(np.std(hs)) if len(hs) > 1 else 0.0
    return MarketFeatures(h, a, disp, len(g.venues), h - a)
