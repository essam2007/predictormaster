"""Reconnection + state reconciliation.

After any WS gap we never assume local state is correct: we re-fetch broker positions and
orders and compare before resuming. This module holds the pure comparison logic; the
runtime owns the reconnect loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReconcileResult:
    in_sync: bool
    local_qty: int
    broker_qty: int
    note: str = ""


def reconcile_position(local_qty: int, broker_qty: int) -> ReconcileResult:
    if local_qty == broker_qty:
        return ReconcileResult(True, local_qty, broker_qty, "in sync")
    return ReconcileResult(
        False, local_qty, broker_qty,
        f"DESYNC: local={local_qty} broker={broker_qty}; trusting broker",
    )
