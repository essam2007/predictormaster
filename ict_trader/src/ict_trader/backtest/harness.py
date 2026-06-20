"""Backtest harness: replay feed -> the SAME SignalPipeline -> SimBroker -> trades.

Because it reuses ``SignalPipeline`` verbatim, backtest detection logic is identical to
live. Only the feed (replay) and broker (simulated) differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clock import ET, SessionClock
from ..config import INSTRUMENTS
from ..domain.enums import Symbol, Timeframe
from ..domain.signals import EntryIntent, SetupSnapshot
from ..domain.trades import Trade
from ..engine.pipeline import SignalPipeline
from ..execution.risk import RiskEngine
from .sim_broker import SimBroker


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    setups: list[SetupSnapshot] = field(default_factory=list)
    n_signals: int = 0  # gated_pass setups

    @property
    def n_trades(self) -> int:
        return len(self.trades)


class Backtester:
    def __init__(
        self,
        feed,
        *,
        traded: Symbol = Symbol.NQ,
        clock: SessionClock | None = None,
        risk: RiskEngine | None = None,
        slippage_points: float = 0.25,
    ) -> None:
        self.feed = feed
        self.traded = traded
        self.pipeline = SignalPipeline(clock, traded=traded)
        self.risk = risk or RiskEngine()
        self.point_value = INSTRUMENTS[traded].point_value
        self.broker = SimBroker(point_value=self.point_value, slippage_points=slippage_points)

    def run(self) -> BacktestResult:
        result = BacktestResult()
        traded5m: list = []
        bar_index: dict = {}
        intents: list[tuple[int, EntryIntent]] = []
        last_seen = None

        # -- pass 1: build the signal + bar timeline --------------------
        for m1 in self.feed.iter_bars():
            results = self.pipeline.on_minute_bar(m1)
            cb = self.pipeline.state.closed_bars(self.traded, Timeframe.M5)
            if cb and cb[-1].ts_open != last_seen:
                last_seen = cb[-1].ts_open
                bar_index[cb[-1].ts_open] = len(traded5m)
                traded5m.append(cb[-1])
            for snap, intent in results:
                result.setups.append(snap)
                if intent is not None and snap.gated_pass:
                    result.n_signals += 1
                    idx = bar_index.get(intent.ts, len(traded5m) - 1)
                    intents.append((idx, intent))

        # -- pass 2: simulate positions (1 concurrent, risk gated) ------
        intents.sort(key=lambda x: x[1].ts)
        busy_until = None
        cur_date = None
        for idx, intent in intents:
            d = intent.ts.astimezone(ET).date()
            if cur_date != d:
                self.risk.reset_day()
                cur_date = d
            if busy_until is not None and intent.ts <= busy_until:
                continue
            ok, _reason = self.risk.can_enter()
            if not ok:
                continue
            stop_pts = abs(intent.entry_px - intent.stop_px)
            qty = self.risk.size_for(self.traded, stop_pts, self.point_value)
            if qty <= 0:
                continue
            future = traded5m[idx + 1 :]
            if not future:
                continue
            self.risk.on_open()
            trade = self.broker.run_position(intent, qty, future, self.traded)
            if trade is None:
                self.risk.open_positions = max(0, self.risk.open_positions - 1)
                continue
            self.risk.on_close(trade.realized_pnl)
            busy_until = trade.exit_ts
            result.trades.append(trade)
        return result
