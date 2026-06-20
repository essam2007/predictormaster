"""Kill switch — manual or automatic global halt.

When active, the runtime must cancel working orders, optionally flatten, and block new
intents. Triggers: manual toggle, daily-loss breach, repeated order rejects, feed loss,
ES/NQ desync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class KillSwitch:
    active: bool = False
    reason: str = ""
    activated_at: datetime | None = None
    reject_count: int = 0
    reject_threshold: int = 3
    history: list[dict] = field(default_factory=list)

    def activate(self, reason: str) -> None:
        if self.active:
            return
        self.active = True
        self.reason = reason
        self.activated_at = datetime.now(UTC)
        self.history.append({"ts": self.activated_at.isoformat(), "action": "activate",
                             "reason": reason})

    def deactivate(self) -> None:
        self.active = False
        self.reason = ""
        self.reject_count = 0
        self.history.append({"ts": datetime.now(UTC).isoformat(),
                             "action": "deactivate"})

    def on_order_reject(self) -> None:
        self.reject_count += 1
        if self.reject_count >= self.reject_threshold:
            self.activate(f"{self.reject_count} consecutive order rejects")

    def on_feed_loss(self) -> None:
        self.activate("market-data feed loss")

    def on_desync(self) -> None:
        self.activate("ES/NQ feed desync")

    def can_trade(self) -> bool:
        return not self.active
