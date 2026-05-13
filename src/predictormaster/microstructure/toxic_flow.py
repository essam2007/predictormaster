"""Toxic-flow (adverse-selection) classifier — VPIN family.

Why this matters for α4
-----------------------
α4 is a *liquidity-providing* strategy: we earn the spread by resting
limit orders. The dominant cost of resting limit orders is **adverse
selection** — when an informed trader hits our bid (or lifts our ask),
the price moves AGAINST our new position before we can unwind. The
classic signature: VPIN ↑ ⇒ price about to move ⇒ pull quotes.

Easley, López de Prado, and O'Hara (2012) introduced VPIN — "Volume-
synchronized Probability of Informed Trading." Their key insight: in
high-frequency settings, calendar time is the wrong clock; *volume
time* is the right one because information arrives clustered around
trade events.

Bulk Volume Classification (BVC)
-------------------------------
Without trade-by-trade buyer/seller identification (which Polymarket
does NOT expose), we estimate buy/sell volume using BVC:

    V_buy_τ = V_τ · Φ((p_τ - p_{τ-1}) / (σ_p · √V_τ))

where Φ is the standard normal CDF, σ_p is the rolling std of price
changes. Intuition: a large positive price change concurrent with
large volume implies most of that volume was buying.

VPIN per volume bucket τ:

    VPIN_τ = E_n[|V_buy − V_sell|] / V

where the expectation is taken over the trailing n volume buckets.
High VPIN (above some threshold, typically the 90-95th percentile of
its own history) signals informed order flow.

Quote-pull policy
-----------------
When VPIN exceeds ``vpin_threshold``, the ``ToxicFlowGate`` flips to
"DEFENSIVE" and the strategy:
  1. Cancels all resting maker orders for that token.
  2. Widens any new quotes by a factor ``defensive_widen_bps``.
  3. Stays defensive for a cool-off period ``cool_off_seconds``.

Returns to "NORMAL" when VPIN drops below ``vpin_threshold *
hysteresis`` (default 0.8) AND the cool-off has elapsed. Hysteresis
prevents thrashing on a value oscillating around the threshold.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class FlowRegime(Enum):
    NORMAL = "normal"
    DEFENSIVE = "defensive"


@dataclass(frozen=True)
class VPINBucket:
    """One completed volume bucket."""
    ts_utc: datetime
    volume_total: float
    volume_buy: float
    volume_sell: float
    imbalance: float            # |V_buy - V_sell|


@dataclass
class BVCClassifier:
    """Classifies bulk volume into buy/sell components using the BVC
    estimator (Easley-LdP-O'Hara 2012, eq. 2).

    The classifier maintains a rolling std of price changes for the
    BVC normalisation. ``ddof=1`` for an unbiased estimate.
    """
    price_window: int = 60      # rolling window for σ_p (in observations)
    _prev_price: float | None = None
    _price_changes: deque[float] = field(
        default_factory=lambda: deque(maxlen=60),
    )

    def __post_init__(self):
        self._price_changes = deque(maxlen=self.price_window)

    def classify(self, price: float, volume: float) -> tuple[float, float]:
        """Return (buy_volume, sell_volume) for a single (price, volume)
        observation. Falls back to a 50/50 split before sufficient
        history is accumulated."""
        if volume <= 0:
            return (0.0, 0.0)
        if self._prev_price is None:
            self._prev_price = price
            return (0.5 * volume, 0.5 * volume)
        dp = price - self._prev_price
        self._price_changes.append(dp)
        self._prev_price = price
        if len(self._price_changes) < 5:
            return (0.5 * volume, 0.5 * volume)
        sigma_p = float(np.std(self._price_changes, ddof=1))
        if sigma_p <= 0:
            return (0.5 * volume, 0.5 * volume)
        # The denominator scales σ_p by √V (Easley-LdP-O'Hara eq. 2).
        # We use the standard normal CDF — substitute Student-t for
        # heavier tails if needed.
        z = dp / (sigma_p * np.sqrt(volume))
        cdf_z = float(stats.norm.cdf(z))
        v_buy = cdf_z * volume
        v_sell = volume - v_buy
        return (v_buy, v_sell)


@dataclass
class VPINEstimator:
    """Volume-bucketed VPIN.

    The estimator accumulates incoming (price, volume) observations
    into volume buckets of size ``bucket_volume``. Each completed
    bucket contributes one ``VPINBucket`` to the history. The current
    VPIN is the mean of ``|V_buy − V_sell|`` over the last
    ``n_buckets`` buckets.
    """
    bucket_volume: float
    n_buckets: int = 50
    bvc: BVCClassifier = field(default_factory=BVCClassifier)
    _current_vol: float = 0.0
    _current_buy: float = 0.0
    _current_sell: float = 0.0
    _history: deque[VPINBucket] = field(
        default_factory=lambda: deque(maxlen=50),
    )

    def __post_init__(self):
        self._history = deque(maxlen=self.n_buckets)

    def update(self, ts: datetime, price: float, volume: float) -> float | None:
        """Add one observation. Returns the current VPIN if a bucket
        completed on this tick, else None."""
        v_buy, v_sell = self.bvc.classify(price, volume)
        self._current_buy += v_buy
        self._current_sell += v_sell
        self._current_vol += volume
        completed: float | None = None
        while self._current_vol >= self.bucket_volume:
            # Roll a bucket and carry the overflow into the next one.
            overflow = self._current_vol - self.bucket_volume
            frac_in = (self.bucket_volume / self._current_vol) if self._current_vol > 0 else 0.0
            buy_in = self._current_buy * frac_in
            sell_in = self._current_sell * frac_in
            self._history.append(VPINBucket(
                ts_utc=ts, volume_total=self.bucket_volume,
                volume_buy=buy_in, volume_sell=sell_in,
                imbalance=abs(buy_in - sell_in),
            ))
            self._current_buy -= buy_in
            self._current_sell -= sell_in
            self._current_vol = overflow
            completed = self._vpin()
        return completed

    def _vpin(self) -> float:
        if not self._history:
            return 0.0
        return float(
            np.mean([b.imbalance for b in self._history]) / self.bucket_volume
        )

    @property
    def current(self) -> float:
        """Cheap accessor — recomputes from history (O(n_buckets))."""
        return self._vpin()

    @property
    def n_complete(self) -> int:
        return len(self._history)


# ---------------- Gate ----------------

@dataclass
class ToxicFlowGate:
    """State machine: NORMAL ↔ DEFENSIVE with hysteresis.

    Decision rule.
    - In NORMAL: enter DEFENSIVE iff VPIN ≥ vpin_threshold.
    - In DEFENSIVE: return to NORMAL iff
        VPIN ≤ vpin_threshold * hysteresis  AND
        now ≥ entered_defensive_at + cool_off

    The gate exposes:
      - ``regime``       — current state
      - ``should_pull()``  — True ⇒ cancel all resting maker orders
      - ``widen_factor()`` — multiply target spread by this factor
    """
    vpin_threshold: float = 0.30
    hysteresis: float = 0.80
    defensive_widen_factor: float = 2.0
    cool_off_seconds: int = 60
    regime: FlowRegime = FlowRegime.NORMAL
    _entered_defensive_at: datetime | None = None
    _last_vpin: float = 0.0

    def update(self, vpin: float, now: datetime) -> FlowRegime:
        self._last_vpin = vpin
        if self.regime is FlowRegime.NORMAL:
            if vpin >= self.vpin_threshold:
                logger.info("toxic flow → DEFENSIVE  (vpin=%.3f ≥ %.3f)",
                            vpin, self.vpin_threshold)
                self.regime = FlowRegime.DEFENSIVE
                self._entered_defensive_at = now
        else:    # DEFENSIVE
            exit_threshold = self.vpin_threshold * self.hysteresis
            cool_off_done = (
                self._entered_defensive_at is not None
                and now - self._entered_defensive_at
                >= timedelta(seconds=self.cool_off_seconds)
            )
            if vpin <= exit_threshold and cool_off_done:
                logger.info("toxic flow → NORMAL     (vpin=%.3f ≤ %.3f, cool-off ok)",
                            vpin, exit_threshold)
                self.regime = FlowRegime.NORMAL
                self._entered_defensive_at = None
        return self.regime

    def should_pull(self) -> bool:
        """True ⇒ the strategy should cancel all resting maker orders.

        Triggered on entry to DEFENSIVE. The strategy is responsible
        for tracking which orders are resting; this gate only signals
        the policy, never executes it.
        """
        return self.regime is FlowRegime.DEFENSIVE

    def widen_factor(self) -> float:
        return self.defensive_widen_factor if self.regime is FlowRegime.DEFENSIVE else 1.0


# ---------------- Combined: features + gate ----------------

@dataclass
class ToxicFlowState:
    """Convenience wrapper bundling the VPIN estimator and gate.

    Drives both off a single stream of (ts, price, volume) ticks. Use
    this from the live strategy loop; instantiate one per token_id
    (the gate state is per-instrument).
    """
    estimator: VPINEstimator
    gate: ToxicFlowGate = field(default_factory=ToxicFlowGate)

    def feed(self, ts: datetime, price: float, volume: float) -> tuple[FlowRegime, float]:
        """Single-call update. Returns (current_regime, current_vpin)."""
        new_vpin = self.estimator.update(ts, price, volume)
        if new_vpin is not None:
            self.gate.update(new_vpin, ts)
        return (self.gate.regime, self.estimator.current)
