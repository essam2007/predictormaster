from __future__ import annotations

from datetime import datetime

from ict_trader.clock import ET, SessionClock
from ict_trader.detectors.timefilter import DayFilterDetector, TimingDetector
from ict_trader.domain.enums import Side


def _clock():
    return SessionClock()


def test_timing_present_in_silver_bullet_wed():
    det = TimingDetector(_clock())
    st = det.update(datetime(2024, 5, 15, 10, 5, tzinfo=ET), Side.LONG, daily_extreme_in=False)
    assert st.present is True
    assert st.payload["killzone"] == "silver_bullet"
    assert st.confidence >= 0.9  # silver bullet / macro -> high confidence


def test_timing_blocked_when_daily_extreme_in():
    det = TimingDetector(_clock())
    st = det.update(datetime(2024, 5, 15, 10, 5, tzinfo=ET), Side.LONG, daily_extreme_in=True)
    assert st.present is False


def test_timing_blocked_during_news_window():
    det = TimingDetector(_clock())
    st = det.update(datetime(2024, 5, 15, 8, 30, tzinfo=ET), Side.LONG, daily_extreme_in=False)
    assert st.present is False
    assert st.payload["is_news_block"] is True


def test_timing_outside_killzone():
    det = TimingDetector(_clock())
    st = det.update(datetime(2024, 5, 15, 13, 0, tzinfo=ET), Side.LONG, daily_extreme_in=False)
    assert st.present is False


def test_dayfilter_prefers_tue_wed_rejects_fri():
    det = DayFilterDetector(_clock())
    tue = det.update(datetime(2024, 5, 14, 9, 0, tzinfo=ET), Side.LONG)
    fri = det.update(datetime(2024, 5, 17, 9, 0, tzinfo=ET), Side.LONG)
    assert tue.present is True and tue.payload["is_preferred_day"] is True
    assert fri.present is False and fri.payload["is_avoid_day"] is True
