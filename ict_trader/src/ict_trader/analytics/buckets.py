"""Analysis dimensions — the buckets the research insists we slice performance by."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.trades import Trade

_DOW = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

# name -> function mapping a Trade to its bucket label
BUCKETS: dict[str, Callable[[Trade], str]] = {
    "day_of_week": lambda t: _DOW.get(t.day_of_week, "?"),
    "killzone": lambda t: t.killzone.value,
    "quarter_idx": lambda t: f"Q{t.quarter_idx}",
    "amd_phase": lambda t: t.amd_phase.value,
    "daily_extreme_in": lambda t: "extreme_in" if t.daily_extreme_in else "extreme_open",
    "path_clean": lambda t: "clean" if t.path_clean else "congested",
    "moved_to_be_early": lambda t: "be_early" if t.moved_to_be_early else "no_be_early",
    "exit_reason": lambda t: t.exit_reason.value if t.exit_reason else "none",
}
