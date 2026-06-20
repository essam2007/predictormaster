"""The signal pipeline: wires market state + detectors + aggregator.

This is the shared brain used by BOTH the live runtime and the backtest harness. It is
synchronous and side-effect-free beyond updating ``MarketState``; callers decide what to do
with the emitted setups/intents.
"""

from __future__ import annotations

from datetime import datetime

from ..clock import SessionClock
from ..confluence.aggregator import ConfluenceAggregator
from ..detectors.fvg import FVGDetector, detect_fvgs, resolve_fills
from ..detectors.ifvg import LTFTriggerDetector
from ..detectors.lrlr import LRLRDetector
from ..detectors.psp import PSPDetector
from ..detectors.quarterly import refine_amd
from ..detectors.smt import SMTDetector
from ..detectors.timefilter import DayFilterDetector, TimingDetector
from ..domain.bars import Bar
from ..domain.enums import ComponentId, Side, Symbol, Timeframe
from ..domain.pdarrays import FVG
from ..domain.signals import ComponentState, EntryIntent, SetupSnapshot
from .state import MarketState, align_closed


def _absent(component: ComponentId, bias: Side, ts: datetime | None = None) -> ComponentState:
    return ComponentState(component, present=False, bias=bias, ts=ts)

# timeframe roles
HTF = (Timeframe.M15, Timeframe.H1)
TRIGGER_TF = Timeframe.M5


class SignalPipeline:
    def __init__(
        self,
        clock: SessionClock | None = None,
        *,
        traded: Symbol = Symbol.NQ,
        tick_size: float = 0.25,
    ) -> None:
        self.clock = clock or SessionClock()
        self.traded = traded
        self.state = MarketState()
        self.fvg = FVGDetector(tick_size=tick_size)
        self.ltf = LTFTriggerDetector(tick_size=tick_size)
        self.smt1 = SMTDetector(stage=1)
        self.smt2 = SMTDetector(stage=2)
        self.psp = PSPDetector()
        self.timing = TimingDetector(self.clock)
        self.dayfilter = DayFilterDetector(self.clock)
        self.aggregator = ConfluenceAggregator()

    def on_minute_bar(self, m1: Bar) -> list[tuple[SetupSnapshot, EntryIntent | None]]:
        """Feed a 1-minute bar; evaluate confluence when the trigger timeframe closes."""
        closed = self.state.on_minute_bar(m1)
        if TRIGGER_TF not in closed:
            return []
        # Only evaluate once per trigger close, anchored on the traded symbol's bar.
        if closed[TRIGGER_TF].symbol is not self.traded:
            return []
        ts = closed[TRIGGER_TF].ts_open
        results = []
        for bias in (Side.LONG, Side.SHORT):
            snap, intent = self._evaluate(ts, bias)
            results.append((snap, intent))
        return results

    def _evaluate(self, ts: datetime, bias: Side) -> tuple[SetupSnapshot, EntryIntent | None]:
        st = self.state
        states = {}

        # FVG bias on HTF (prefer the higher TF if both present)
        fvg_state = None
        for tf in HTF:
            bars = st.closed_bars(self.traded, tf)
            cand = self.fvg.update(bars, tf, bias)
            if cand.present:
                fvg_state = cand
                break
        states[ComponentId.FVG] = fvg_state or self.fvg.update(
            st.closed_bars(self.traded, Timeframe.M15), Timeframe.M15, bias
        )

        # SMT stage-1 on 15m, stage-2 nested on 5m
        es15, nq15 = align_closed(
            st.closed_bars(Symbol.ES, Timeframe.M15), st.closed_bars(Symbol.NQ, Timeframe.M15)
        )
        states[ComponentId.SMT1] = self.smt1.update(es15, nq15, bias)
        es5, nq5 = align_closed(
            st.closed_bars(Symbol.ES, TRIGGER_TF), st.closed_bars(Symbol.NQ, TRIGGER_TF)
        )
        states[ComponentId.SMT2] = self.smt2.update(es5[-18:], nq5[-18:], bias)

        # PSP on the latest 5m co-bar; flag if inside the HTF FVG
        cobar = st.latest_cobar(TRIGGER_TF)
        inside = False
        if cobar and not cobar.degraded and fvg_state and fvg_state.present and cobar.nq:
            lo, hi = fvg_state.payload["lower"], fvg_state.payload["upper"]
            inside = lo <= cobar.nq.close <= hi
        if cobar is not None:
            states[ComponentId.PSP] = self.psp.update(cobar, bias, inside_htf_fvg=inside)
        else:
            states[ComponentId.PSP] = _absent(ComponentId.PSP, bias, ts)

        # LTF trigger on 5m
        ltf_state = self.ltf.update(st.closed_bars(self.traded, TRIGGER_TF), TRIGGER_TF, bias)
        states[ComponentId.LTF_TRIGGER] = ltf_state

        # timing / day filter
        liq = st.liquidity[self.traded]
        last_close = (
            st.closed_bars(self.traded, TRIGGER_TF)[-1].close
            if st.closed_bars(self.traded, TRIGGER_TF)
            else 0.0
        )
        extreme_in = liq.daily_extreme_in(bias, last_close)
        timing_state = self.timing.update(ts, bias, daily_extreme_in=extreme_in)
        # annotate AMD phase onto timing payload for the snapshot
        q_idx = int(timing_state.payload.get("quarter_idx", -1))
        timing_state.payload["amd"] = refine_amd(
            q_idx, st.closed_bars(self.traded, TRIGGER_TF)[-6:]
        ).value
        states[ComponentId.TIMING] = timing_state
        states[ComponentId.DAYFILTER] = self.dayfilter.update(ts, bias)

        # LRLR: scan opposing arrays between entry and ERL target
        erl = liq.erl_target(bias)
        arrays = self._active_arrays(bias)
        entry_px = float(ltf_state.payload["entry"]) if ltf_state.present else last_close
        if erl is not None:
            states[ComponentId.LRLR] = LRLRDetector().update(entry_px, erl, bias, arrays)
        else:
            states[ComponentId.LRLR] = _absent(ComponentId.LRLR, bias, ts)

        return self.aggregator.evaluate(
            ts, bias, states, erl_target=erl, daily_extreme_in=extreme_in
        )

    def _active_arrays(self, bias: Side) -> list[FVG]:
        arrays: list[FVG] = []
        for tf in (TRIGGER_TF, Timeframe.M15):
            bars = self.state.closed_bars(self.traded, tf)
            fvgs = detect_fvgs(bars, tf)
            resolve_fills(fvgs, bars)
            arrays.extend(f for f in fvgs if not f.filled)
        return arrays
