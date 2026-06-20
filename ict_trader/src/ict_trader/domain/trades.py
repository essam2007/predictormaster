"""Order / fill / trade value objects and the management-event audit record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    OrderStatus,
    OrderType,
    Side,
    Symbol,
    TradeMode,
)


@dataclass(slots=True)
class Order:
    symbol: Symbol
    side: Side
    order_type: OrderType
    qty: int
    price: float | None = None
    stop_price: float | None = None
    idempotency_key: str = ""
    broker_order_id: str | None = None
    parent_id: str | None = None
    status: OrderStatus = OrderStatus.PENDING
    ts: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Fill:
    order_idempotency_key: str
    qty: int
    price: float
    ts: datetime
    commission: float = 0.0
    broker_fill_id: str | None = None


@dataclass(slots=True)
class ManagementEvent:
    """An audit row for every position action (partial / trail / breakeven move)."""

    ts: datetime
    event: str  # partial | trail_move | be_move | reduce | stop_replaced
    from_px: float | None
    to_px: float | None
    structure_ref: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(slots=True)
class Trade:
    """A realized round-trip — the analysis spine of the research deck.

    Carries every per-condition tag the strategy wants to slice by, including the critical
    ``moved_to_be_early`` flag and ``be_trigger`` reason.
    """

    symbol: Symbol
    side: Side
    entry_ts: datetime
    entry_px: float
    qty_initial: int
    mode: TradeMode
    # exit / outcome (filled in on close)
    exit_ts: datetime | None = None
    exit_px: float | None = None
    realized_pnl: float = 0.0
    realized_r: float = 0.0
    mae_r: float = 0.0  # max adverse excursion in R
    mfe_r: float = 0.0  # max favorable excursion in R
    risk_per_contract: float = 0.0
    # per-condition tags (the buckets)
    day_of_week: int = -1
    killzone: Killzone = Killzone.NONE
    quarter_idx: int = -1
    amd_phase: AMDPhase = AMDPhase.UNKNOWN
    daily_extreme_in: bool = False
    path_clean: bool = False
    moved_to_be_early: bool = False
    be_trigger: BreakevenTrigger = BreakevenTrigger.NONE
    partials_taken: int = 0
    runner_held: bool = False
    runner_hit_erl: bool = False
    exit_reason: ExitReason | None = None
    setup_score: float = 0.0
    events: list[ManagementEvent] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.exit_ts is None
