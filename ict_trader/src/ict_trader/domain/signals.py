"""Signal value objects: per-component state, a confluence snapshot, and an entry intent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import AMDPhase, ComponentId, Killzone, Side


@dataclass(slots=True)
class ComponentState:
    """The output of a single detector at a bar close.

    ``payload`` carries the full detector output (gap bounds, swept level, refs, ...) so it
    can be persisted and later mined for calibration without recomputation.
    """

    component: ComponentId
    present: bool
    bias: Side = Side.NONE
    confidence: float = 0.0  # 0..1
    ts: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SetupSnapshot:
    """A full confluence evaluation at one moment — persisted whether or not it passes.

    The nine component booleans are denormalized so the research deck's per-bucket
    analytics are single-table GROUP BYs.
    """

    ts: datetime
    bias: Side
    # nine components
    fvg_ok: bool = False
    smt1_ok: bool = False
    smt2_ok: bool = False
    psp_ok: bool = False
    ltf_trigger_ok: bool = False
    lrlr_ok: bool = False
    timing_ok: bool = False
    dayfilter_ok: bool = False
    management_ok: bool = False
    # analysis dimensions
    daily_extreme_in: bool = False
    path_clean: bool = False
    killzone: Killzone = Killzone.NONE
    quarter_idx: int = -1
    amd_phase: AMDPhase = AMDPhase.UNKNOWN
    # scoring + plan
    score: float = 0.0
    gated_pass: bool = False
    entry_px: float | None = None
    stop_px: float | None = None
    tp1_px: float | None = None
    tp2_px: float | None = None
    runner_target_px: float | None = None
    planned_risk_r: float | None = None
    components: dict[str, Any] = field(default_factory=dict)

    @property
    def stack_count(self) -> int:
        return sum(
            [
                self.fvg_ok,
                self.smt1_ok,
                self.smt2_ok,
                self.psp_ok,
                self.ltf_trigger_ok,
                self.lrlr_ok,
                self.timing_ok,
                self.dayfilter_ok,
                self.management_ok,
            ]
        )


@dataclass(slots=True)
class EntryIntent:
    """A decision to enter, produced by the confluence aggregator."""

    ts: datetime
    side: Side
    entry_px: float
    stop_px: float
    tp1_px: float
    tp2_px: float
    runner_target_px: float
    risk_r: float
    setup: SetupSnapshot
    reason: str = ""

    @property
    def stop_distance(self) -> float:
        return abs(self.entry_px - self.stop_px)
