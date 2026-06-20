"""Position sizing and risk limits — shared by live and backtest.

Pure functions where possible so they are trivially unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor

from ..domain.enums import Symbol


def position_size(
    *,
    per_trade_usd: float,
    stop_distance_points: float,
    point_value: float,
    max_contracts: int,
) -> int:
    """Contracts such that (stop distance x point value x contracts) ~ per-trade risk.

    Returns 0 when the stop is degenerate or the risk budget can't afford one contract.
    """
    if stop_distance_points <= 0 or point_value <= 0:
        return 0
    risk_per_contract = stop_distance_points * point_value
    if risk_per_contract <= 0:
        return 0
    n = floor(per_trade_usd / risk_per_contract)
    return max(0, min(n, max_contracts))


@dataclass
class RiskEngine:
    """Tracks daily risk usage and enforces hard limits."""

    per_trade_usd: float = 250.0
    daily_loss_limit_usd: float = 750.0
    max_concurrent_positions: int = 1
    max_contracts: int = 3
    # mutable state
    daily_loss_used: float = 0.0
    open_positions: int = 0
    halted: bool = False
    halt_reason: str = ""
    _instruments: dict[Symbol, float] = field(default_factory=dict)

    def can_enter(self) -> tuple[bool, str]:
        if self.halted:
            return False, f"halted: {self.halt_reason}"
        if self.open_positions >= self.max_concurrent_positions:
            return False, "max concurrent positions"
        if self.daily_loss_used >= self.daily_loss_limit_usd:
            return False, "daily loss limit reached"
        return True, ""

    def size_for(
        self, symbol: Symbol, stop_distance_points: float, point_value: float
    ) -> int:
        return position_size(
            per_trade_usd=self.per_trade_usd,
            stop_distance_points=stop_distance_points,
            point_value=point_value,
            max_contracts=self.max_contracts,
        )

    def on_open(self) -> None:
        self.open_positions += 1

    def on_close(self, realized_pnl: float) -> None:
        self.open_positions = max(0, self.open_positions - 1)
        if realized_pnl < 0:
            self.daily_loss_used += -realized_pnl
            if self.daily_loss_used >= self.daily_loss_limit_usd:
                self.halt("daily loss limit reached")

    def halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason

    def reset_day(self) -> None:
        self.daily_loss_used = 0.0
        self.halted = False
        self.halt_reason = ""
