from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ict_trader.analytics.setup_scanner import SetupCandidate, killzone_et, scan
from ict_trader.domain.bars import Bar
from ict_trader.domain.enums import Killzone, Symbol, Timeframe

ET = ZoneInfo("America/New_York")


def test_killzone_et_windows():
    def at(h, m):
        return datetime(2026, 6, 16, h, m, tzinfo=ET)
    assert killzone_et(at(9, 45)) is Killzone.NY_AM
    assert killzone_et(at(10, 30)) is Killzone.SILVER_BULLET  # SB is a subset of NY-AM
    assert killzone_et(at(11, 30)) is Killzone.NY_AM
    assert killzone_et(at(9, 0)) is Killzone.NONE              # pre-open
    assert killzone_et(at(13, 0)) is Killzone.NONE             # afternoon


def _flat(n: int) -> tuple[list[Bar], list[Bar]]:
    start = datetime(2026, 6, 16, 9, 30, tzinfo=ET)
    mk = lambda i, px: Bar(symbol=Symbol.NQ, timeframe=Timeframe.M5,  # noqa: E731
                           ts_open=start + timedelta(minutes=5 * i),
                           open=px, high=px + 1, low=px - 1, close=px, volume=1)
    nq = [mk(i, 21000.0) for i in range(n)]
    es = [mk(i, 6000.0) for i in range(n)]
    return nq, es


def test_scan_mismatched_lengths_raises():
    nq, es = _flat(10)
    with pytest.raises(ValueError):
        scan(nq, es[:-1])


def test_scan_flat_data_returns_list_no_crash():
    nq, es = _flat(60)
    cands = scan(nq, es)
    assert isinstance(cands, list)
    # flat data has no FVGs/IFVGs to trigger on → no candidates
    assert all(isinstance(c, SetupCandidate) for c in cands)
