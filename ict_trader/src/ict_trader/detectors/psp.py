"""Precision Swing Point (PSP) — candle-level SMT inversion.

At the same timestamp, one index closes bullish while the other closes bearish (opposing
closes). For a long setup the truth-teller (holder, e.g. NQ) should close up while the
other closes down. Dojis are excluded. Weighted higher when the PSP candle is inside the
HTF FVG.
"""

from __future__ import annotations

from ..domain.bars import Bar, CoBar
from ..domain.enums import ComponentId, Side
from ..domain.signals import ComponentState


def is_psp(es: Bar, nq: Bar) -> bool:
    """True when ES and NQ have opposing (non-doji) directional closes at the same bar."""
    if es.is_doji or nq.is_doji:
        return False
    return (es.is_bullish and nq.is_bearish) or (es.is_bearish and nq.is_bullish)


class PSPDetector:
    component = ComponentId.PSP

    def update(
        self,
        cobar: CoBar,
        side: Side,
        *,
        inside_htf_fvg: bool = False,
    ) -> ComponentState:
        if cobar.degraded or cobar.es is None or cobar.nq is None:
            return ComponentState(self.component, present=False, bias=side,
                                  payload={"degraded": True})
        es, nq = cobar.es, cobar.nq
        if not is_psp(es, nq):
            return ComponentState(self.component, present=False, bias=side, ts=cobar.ts_open)

        nq_dir = Side.LONG if nq.is_bullish else Side.SHORT
        es_dir = Side.LONG if es.is_bullish else Side.SHORT
        # Agreement: the bias-direction close should come from one of the two indices.
        agrees = side in (nq_dir, es_dir)
        conf = 0.6 + (0.2 if inside_htf_fvg else 0.0) + (0.1 if agrees else -0.2)
        return ComponentState(
            self.component, present=agrees, bias=side,
            confidence=round(max(0.0, min(1.0, conf)), 3), ts=cobar.ts_open,
            payload={"nq_dir": nq_dir.value, "es_dir": es_dir.value,
                     "inside_htf_fvg": inside_htf_fvg},
        )
