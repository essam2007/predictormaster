"""Typed read/write helpers. The ONLY place app code touches the DB, so the SQLite ->
Postgres/Timescale switch is a DSN change plus one migration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import (
    AMDPhase,
    BreakevenTrigger,
    ExitReason,
    Killzone,
    Side,
    Symbol,
    TradeMode,
)
from ..domain.signals import SetupSnapshot
from ..domain.trades import ManagementEvent, Trade
from .models import EquityRow, OrderRow, SetupRow, TradeRow, WebhookAlertRow


def setup_to_row(s: SetupSnapshot, mode: TradeMode) -> SetupRow:
    return SetupRow(
        ts=s.ts, mode=mode.value, bias=s.bias.value,
        fvg_ok=s.fvg_ok, smt1_ok=s.smt1_ok, smt2_ok=s.smt2_ok, psp_ok=s.psp_ok,
        ltf_trigger_ok=s.ltf_trigger_ok, lrlr_ok=s.lrlr_ok, timing_ok=s.timing_ok,
        dayfilter_ok=s.dayfilter_ok, management_ok=s.management_ok,
        daily_extreme_in=s.daily_extreme_in, path_clean=s.path_clean,
        killzone=s.killzone.value, quarter_idx=s.quarter_idx, amd_phase=s.amd_phase.value,
        score=s.score, gated_pass=s.gated_pass, entry_px=s.entry_px, stop_px=s.stop_px,
        runner_target_px=s.runner_target_px, planned_risk_r=s.planned_risk_r,
        components=s.components,
    )


def trade_to_row(t: Trade) -> TradeRow:
    return TradeRow(
        mode=t.mode.value, symbol=t.symbol.value, side=t.side.value,
        entry_ts=t.entry_ts, entry_px=t.entry_px, exit_ts=t.exit_ts, exit_px=t.exit_px,
        qty_initial=t.qty_initial, realized_pnl=t.realized_pnl, realized_r=t.realized_r,
        mae_r=t.mae_r, mfe_r=t.mfe_r, day_of_week=t.day_of_week, killzone=t.killzone.value,
        quarter_idx=t.quarter_idx, amd_phase=t.amd_phase.value,
        daily_extreme_in=t.daily_extreme_in, path_clean=t.path_clean,
        moved_to_be_early=t.moved_to_be_early, be_trigger=t.be_trigger.value,
        partials_taken=t.partials_taken, runner_held=t.runner_held,
        runner_hit_erl=t.runner_hit_erl,
        exit_reason=t.exit_reason.value if t.exit_reason else None,
        setup_score=t.setup_score,
        events=[{"ts": e.ts.isoformat(), "event": e.event, "from_px": e.from_px,
                 "to_px": e.to_px, "note": e.note} for e in t.events],
    )


def row_to_trade(r: TradeRow) -> Trade:
    """Reconstruct a domain Trade so the in-memory analytics work on DB rows too."""
    return Trade(
        symbol=Symbol(r.symbol), side=Side(r.side), entry_ts=r.entry_ts, entry_px=r.entry_px,
        qty_initial=r.qty_initial, mode=TradeMode(r.mode), exit_ts=r.exit_ts, exit_px=r.exit_px,
        realized_pnl=r.realized_pnl, realized_r=r.realized_r, mae_r=r.mae_r, mfe_r=r.mfe_r,
        day_of_week=r.day_of_week, killzone=Killzone(r.killzone), quarter_idx=r.quarter_idx,
        amd_phase=AMDPhase(r.amd_phase), daily_extreme_in=r.daily_extreme_in,
        path_clean=r.path_clean, moved_to_be_early=r.moved_to_be_early,
        be_trigger=BreakevenTrigger(r.be_trigger), partials_taken=r.partials_taken,
        runner_held=r.runner_held, runner_hit_erl=r.runner_hit_erl,
        exit_reason=ExitReason(r.exit_reason) if r.exit_reason else None,
        setup_score=r.setup_score,
        events=[ManagementEvent(ts=t["ts"], event=t["event"], from_px=t["from_px"],
                                to_px=t["to_px"], note=t.get("note", "")) for t in (r.events or [])],
    )


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add_setups(self, setups: list[SetupSnapshot], mode: TradeMode) -> None:
        self.s.add_all([setup_to_row(s, mode) for s in setups])
        await self.s.commit()

    async def add_trades(self, trades: list[Trade]) -> None:
        self.s.add_all([trade_to_row(t) for t in trades])
        await self.s.commit()

    async def add_trade(self, trade: Trade) -> None:
        self.s.add(trade_to_row(trade))
        await self.s.commit()

    async def list_trades(self, mode: TradeMode | None = None) -> list[Trade]:
        stmt = select(TradeRow)
        if mode is not None:
            stmt = stmt.where(TradeRow.mode == mode.value)
        rows = (await self.s.execute(stmt.order_by(TradeRow.entry_ts))).scalars().all()
        return [row_to_trade(r) for r in rows]

    async def list_setups(self, mode: TradeMode | None = None) -> list[SetupRow]:
        stmt = select(SetupRow)
        if mode is not None:
            stmt = stmt.where(SetupRow.mode == mode.value)
        return list((await self.s.execute(stmt.order_by(SetupRow.ts))).scalars().all())

    async def log_webhook(self, ts, payload: dict, matched: bool = False) -> None:
        self.s.add(WebhookAlertRow(ts=ts, source="pine", payload=payload, matched=matched))
        await self.s.commit()

    async def list_webhooks(self, limit: int = 100) -> list[WebhookAlertRow]:
        stmt = select(WebhookAlertRow).order_by(WebhookAlertRow.ts.desc()).limit(limit)
        return list((await self.s.execute(stmt)).scalars().all())

    async def add_order(self, row: OrderRow) -> None:
        self.s.add(row)
        await self.s.commit()

    async def record_equity(self, row: EquityRow) -> None:
        self.s.add(row)
        await self.s.commit()
