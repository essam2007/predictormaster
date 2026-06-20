"""Pure fill / PnL helpers shared by the simulated (batch) and paper (streaming) brokers.

Keeping these in one place means the backtest and the live paper loop price entries, stops,
targets and partials identically.
"""

from __future__ import annotations

from ..domain.bars import Bar
from ..domain.enums import ExitReason, Side


def touches(bar: Bar, level: float) -> bool:
    """True if a limit at ``level`` would be touched by this bar."""
    return bar.low <= level <= bar.high


def adverse_first(side: Side, bar: Bar, entry: float, stop: float) -> bool:
    """True if the bar blew past the stop without ever touching the entry (no fill)."""
    if side is Side.LONG:
        return bar.high < entry and bar.low <= stop
    return bar.low > entry and bar.high >= stop


def pnl_points(side: Side, entry: float, exit_px: float) -> float:
    return (exit_px - entry) if side is Side.LONG else (entry - exit_px)


def exit_fill_px(
    side: Side,
    bar: Bar,
    reason: ExitReason | None,
    *,
    stop_px: float,
    runner_target_px: float,
    slippage: float,
) -> float:
    """Realistic exit fill: stops fill at the stop +/- slippage, targets at the limit."""
    if reason in (ExitReason.STOP, ExitReason.TRAIL, ExitReason.BREAKEVEN):
        return stop_px - slippage if side is Side.LONG else stop_px + slippage
    if reason is ExitReason.RUNNER_TARGET:
        return runner_target_px
    return bar.close
