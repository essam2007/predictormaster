"""The single source of truth for time.

Everything time-related — sessions, 90-minute quarters, killzones, macros, the
Silver-Bullet window, day-of-week filters and news blocks — derives from here so there is
exactly one place DST is handled. We key off ``America/New_York`` and never hard-code a
UTC offset.

Quarterly Theory mapping used here (ET):
    Day  = 4 six-hour sessions: Asia 18:00, London 00:00, NY-AM 06:00, NY-PM 12:00
    Each session = 4 x 90-minute quarters.
    The NY-AM quarters are therefore 06:00-07:30, 07:30-09:00, 09:00-10:30, 10:30-12:00.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .domain.enums import AMDPhase, Killzone

ET = ZoneInfo("America/New_York")

# Six-hour session boundaries, expressed as the ET hour at which each session starts.
_SESSION_STARTS = {
    "asia": 18,
    "london": 0,
    "ny_am": 6,
    "ny_pm": 12,
}


@dataclass(frozen=True, slots=True)
class TimeContext:
    """Everything the detectors need to know about *when* a bar closed."""

    et: datetime  # the input time, in ET
    session: str  # asia | london | ny_am | ny_pm
    quarter_idx: int  # 0..3 within the session
    quarter_start: datetime
    quarter_end: datetime
    killzone: Killzone
    is_macro: bool
    is_silver_bullet: bool
    is_news_block: bool
    day_of_week: int  # Monday=0 .. Sunday=6
    is_preferred_day: bool  # Tue/Wed
    is_avoid_day: bool  # Fri (+ weekend)


class SessionClock:
    """Computes a :class:`TimeContext` for any timezone-aware datetime.

    ``news_windows`` is a list of (HH:MM, HH:MM) ET ranges to hard-block (e.g. 08:30
    CPI/NFP, FOMC). They are simple wall-clock ranges applied every day; the engine can
    additionally consult an economic calendar to enable/disable them per date.
    """

    def __init__(
        self,
        *,
        ny_am_killzone: tuple[time, time] = (time(7, 0), time(10, 0)),
        silver_bullet: tuple[time, time] = (time(10, 0), time(11, 0)),
        lunch: tuple[time, time] = (time(11, 0), time(13, 30)),
        news_windows: list[tuple[time, time]] | None = None,
        preferred_days: tuple[int, ...] = (1, 2),  # Tue, Wed
        avoid_days: tuple[int, ...] = (4, 5, 6),  # Fri, Sat, Sun
    ) -> None:
        self.ny_am_killzone = ny_am_killzone
        self.silver_bullet = silver_bullet
        self.lunch = lunch
        self.news_windows = news_windows or [(time(8, 30), time(8, 32))]
        self.preferred_days = preferred_days
        self.avoid_days = avoid_days

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def to_et(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            raise ValueError("SessionClock requires timezone-aware datetimes")
        return dt.astimezone(ET)

    @staticmethod
    def _in_window(t: time, window: tuple[time, time]) -> bool:
        lo, hi = window
        if lo <= hi:
            return lo <= t < hi
        # window wraps past midnight
        return t >= lo or t < hi

    def _session_and_quarter(self, et: datetime) -> tuple[str, datetime]:
        """Return (session_name, session_start_dt) for the given ET time."""
        h = et.hour
        if 18 <= h < 24:
            name, start_h, base = "asia", 18, et
        elif 0 <= h < 6:
            name, start_h, base = "london", 0, et
        elif 6 <= h < 12:
            name, start_h, base = "ny_am", 6, et
        else:  # 12..18
            name, start_h, base = "ny_pm", 12, et
        start = base.replace(hour=start_h, minute=0, second=0, microsecond=0)
        return name, start

    # -- main ------------------------------------------------------------
    def context(self, dt: datetime) -> TimeContext:
        et = self.to_et(dt)
        session, session_start = self._session_and_quarter(et)
        elapsed = et - session_start
        quarter_idx = int(elapsed.total_seconds() // (90 * 60))
        quarter_idx = max(0, min(3, quarter_idx))
        quarter_start = session_start + timedelta(minutes=90 * quarter_idx)
        quarter_end = quarter_start + timedelta(minutes=90)

        t = et.time()
        if self._in_window(t, self.silver_bullet):
            killzone = Killzone.SILVER_BULLET
        elif self._in_window(t, self.ny_am_killzone):
            killzone = Killzone.NY_AM
        elif self._in_window(t, self.lunch):
            killzone = Killzone.LUNCH
        elif session == "london":
            killzone = Killzone.LONDON
        elif session == "asia":
            killzone = Killzone.ASIA
        elif session == "ny_pm":
            killzone = Killzone.NY_PM
        else:
            killzone = Killzone.NONE

        # Macro: the :50-past to :10-past window around each hour.
        minute = et.minute
        is_macro = minute >= 50 or minute <= 10
        is_silver_bullet = killzone is Killzone.SILVER_BULLET
        is_news_block = any(self._in_window(t, w) for w in self.news_windows)

        dow = et.weekday()
        return TimeContext(
            et=et,
            session=session,
            quarter_idx=quarter_idx,
            quarter_start=quarter_start,
            quarter_end=quarter_end,
            killzone=killzone,
            is_macro=is_macro,
            is_silver_bullet=is_silver_bullet,
            is_news_block=is_news_block,
            day_of_week=dow,
            is_preferred_day=dow in self.preferred_days,
            is_avoid_day=dow in self.avoid_days,
        )

    def in_ny_am_killzone(self, dt: datetime) -> bool:
        """True inside the NY-AM killzone OR the Silver-Bullet window (entries allowed)."""
        ctx = self.context(dt)
        return ctx.killzone in (Killzone.NY_AM, Killzone.SILVER_BULLET)


def classify_amd(quarter_idx: int) -> AMDPhase:
    """Default AMD(X) label for a quarter index (Q1 accumulate ... Q3 distribute)."""
    return {
        0: AMDPhase.ACCUMULATION,
        1: AMDPhase.MANIPULATION,
        2: AMDPhase.DISTRIBUTION,
        3: AMDPhase.CONTINUATION,
    }.get(quarter_idx, AMDPhase.UNKNOWN)
