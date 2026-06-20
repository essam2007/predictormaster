"""Timing and day-of-week filter components, built on the SessionClock.

TIMING is a hard gate: we only take entries inside the NY-AM killzone / Silver-Bullet
window, in a quarter that can still set/confirm the daily extreme, and never in a news
block. DAYFILTER prefers Tue/Wed and rejects Fri (and weekends).
"""

from __future__ import annotations

from datetime import datetime

from ..clock import SessionClock, TimeContext
from ..domain.enums import ComponentId, Killzone, Side
from ..domain.signals import ComponentState


class TimingDetector:
    component = ComponentId.TIMING

    def __init__(self, clock: SessionClock) -> None:
        self.clock = clock

    def update(self, ts: datetime, side: Side, *, daily_extreme_in: bool) -> ComponentState:
        ctx: TimeContext = self.clock.context(ts)
        in_window = ctx.killzone in (Killzone.NY_AM, Killzone.SILVER_BULLET)
        present = in_window and not ctx.is_news_block and not daily_extreme_in
        conf = 0.0
        if present:
            conf = 0.9 if (ctx.is_silver_bullet or ctx.is_macro) else 0.7
        return ComponentState(
            self.component, present=present, bias=side, confidence=conf, ts=ts,
            payload={"killzone": ctx.killzone.value, "quarter_idx": ctx.quarter_idx,
                     "is_macro": ctx.is_macro, "is_silver_bullet": ctx.is_silver_bullet,
                     "is_news_block": ctx.is_news_block, "daily_extreme_in": daily_extreme_in},
        )


class DayFilterDetector:
    component = ComponentId.DAYFILTER

    def __init__(self, clock: SessionClock) -> None:
        self.clock = clock

    def update(self, ts: datetime, side: Side) -> ComponentState:
        ctx = self.clock.context(ts)
        present = not ctx.is_avoid_day  # allow Mon-Thu, reject Fri/weekend
        conf = 0.9 if ctx.is_preferred_day else (0.5 if present else 0.0)
        return ComponentState(
            self.component, present=present, bias=side, confidence=conf, ts=ts,
            payload={"day_of_week": ctx.day_of_week,
                     "is_preferred_day": ctx.is_preferred_day,
                     "is_avoid_day": ctx.is_avoid_day},
        )
