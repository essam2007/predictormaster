from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ict_trader.clock import ET, SessionClock, classify_amd
from ict_trader.domain.enums import AMDPhase, Killzone

UTC = ZoneInfo("UTC")


@pytest.fixture
def clock():
    return SessionClock()


def test_ny_am_quarters(clock):
    # 09:00-10:30 ET is NY-AM quarter index 2 (06:00 + 2*90min)
    ctx = clock.context(datetime(2024, 5, 15, 9, 30, tzinfo=ET))
    assert ctx.session == "ny_am"
    assert ctx.quarter_idx == 2
    assert ctx.quarter_start.hour == 9 and ctx.quarter_start.minute == 0


def test_silver_bullet_and_macro(clock):
    ctx = clock.context(datetime(2024, 5, 15, 10, 5, tzinfo=ET))
    assert ctx.killzone is Killzone.SILVER_BULLET
    assert ctx.is_silver_bullet is True
    assert ctx.is_macro is True  # minute 5 <= 10


def test_news_block_at_830(clock):
    ctx = clock.context(datetime(2024, 5, 15, 8, 30, tzinfo=ET))
    assert ctx.is_news_block is True


def test_day_filter_flags(clock):
    tue = clock.context(datetime(2024, 5, 14, 9, 0, tzinfo=ET))  # Tuesday
    fri = clock.context(datetime(2024, 5, 17, 9, 0, tzinfo=ET))  # Friday
    assert tue.is_preferred_day is True and tue.is_avoid_day is False
    assert fri.is_avoid_day is True and fri.is_preferred_day is False


def test_dst_uses_wall_clock_not_fixed_offset(clock):
    # A UTC instant that is 09:30 ET in summer (EDT, UTC-4) vs the same wall time logic.
    # 13:30 UTC == 09:30 EDT on 2024-07-15.
    ctx = clock.context(datetime(2024, 7, 15, 13, 30, tzinfo=UTC))
    assert ctx.et.hour == 9 and ctx.et.minute == 30
    assert ctx.session == "ny_am"


def test_in_ny_am_killzone(clock):
    assert clock.in_ny_am_killzone(datetime(2024, 5, 15, 7, 30, tzinfo=ET)) is True
    assert clock.in_ny_am_killzone(datetime(2024, 5, 15, 12, 30, tzinfo=ET)) is False


def test_classify_amd():
    assert classify_amd(0) is AMDPhase.ACCUMULATION
    assert classify_amd(2) is AMDPhase.DISTRIBUTION


def test_naive_datetime_rejected(clock):
    with pytest.raises(ValueError):
        clock.context(datetime(2024, 5, 15, 9, 30))
