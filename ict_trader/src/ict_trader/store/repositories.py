"""Typed read/write helpers. The ONLY place app code touches the DB, so the SQLite ->
Postgres/Timescale switch is a DSN change plus one migration."""

from __future__ import annotations

from datetime import UTC, datetime

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
from .models import (
    BarRow,
    EquityRow,
    OrderRow,
    SetupRow,
    TradeAnalysisRow,
    TradeRow,
    WebhookAlertRow,
)


def bar_epoch(dt: datetime) -> int:
    """Unix seconds for a bar timestamp, treating naive datetimes as UTC. SQLite reads
    tz-aware columns back as naive, so this keeps write/read/dedup epochs consistent."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


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

    async def add_trade(self, trade: Trade) -> int:
        row = trade_to_row(trade)
        self.s.add(row)
        await self.s.flush()  # assigns the autoincrement PK without expiring on commit
        trade_id = row.id
        await self.s.commit()
        return trade_id

    async def list_trades(self, mode: TradeMode | None = None) -> list[Trade]:
        stmt = select(TradeRow)
        if mode is not None:
            stmt = stmt.where(TradeRow.mode == mode.value)
        rows = (await self.s.execute(stmt.order_by(TradeRow.entry_ts))).scalars().all()
        return [row_to_trade(r) for r in rows]

    async def list_trade_rows(self, mode: TradeMode | None = None) -> list[TradeRow]:
        """Like list_trades but returns ORM rows (with their ids) for joining analysis."""
        stmt = select(TradeRow)
        if mode is not None:
            stmt = stmt.where(TradeRow.mode == mode.value)
        return list((await self.s.execute(stmt.order_by(TradeRow.entry_ts))).scalars().all())

    async def save_trade_analysis(self, trade_id: int, mode: str, analysis: dict) -> None:
        self.s.add(TradeAnalysisRow(
            trade_id=trade_id, mode=mode, score=analysis["score"], grade=analysis["grade"],
            summary=analysis["summary"], elements=analysis["elements"], model=analysis["model"],
            created_at=datetime.now(UTC),
        ))
        await self.s.commit()

    async def get_trade_analysis(self, trade_id: int) -> TradeAnalysisRow | None:
        stmt = (select(TradeAnalysisRow).where(TradeAnalysisRow.trade_id == trade_id)
                .order_by(TradeAnalysisRow.id.desc()).limit(1))
        return (await self.s.execute(stmt)).scalars().first()

    async def analyses_by_trade(self, mode: TradeMode) -> dict[int, TradeAnalysisRow]:
        """Latest analysis per trade for a mode, keyed by trade_id (for the journal)."""
        stmt = (select(TradeAnalysisRow).where(TradeAnalysisRow.mode == mode.value)
                .order_by(TradeAnalysisRow.id))
        out: dict[int, TradeAnalysisRow] = {}
        for r in (await self.s.execute(stmt)).scalars().all():
            out[r.trade_id] = r  # later row (higher id) wins
        return out

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

    async def add_bars(
        self, mode: str, symbol: str, timeframe: str,
        bars: list[dict], source: str = "pine",
    ) -> int:
        """Append OHLC bars, skipping any whose timestamp we already have (idempotent re-sends).

        Each ``bars`` entry is a dict with keys ts (datetime), open, high, low, close, volume.
        Returns the number of NEW rows written.
        """
        if not bars:
            return 0
        existing_ts = (await self.s.execute(
            select(BarRow.ts).where(
                BarRow.mode == mode, BarRow.symbol == symbol, BarRow.timeframe == timeframe,
            )
        )).scalars().all()
        seen = {bar_epoch(t) for t in existing_ts}
        new_rows: list[BarRow] = []
        for b in bars:
            e = bar_epoch(b["ts"])
            if e in seen:  # already stored, or a duplicate within this batch
                continue
            seen.add(e)
            new_rows.append(BarRow(
                mode=mode, symbol=symbol, timeframe=timeframe, ts=b["ts"],
                open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                volume=b.get("volume", 0.0), source=source,
            ))
        self.s.add_all(new_rows)
        await self.s.commit()
        return len(new_rows)

    async def list_bars(
        self, mode: str, symbol: str, timeframe: str, limit: int = 500,
    ) -> list[BarRow]:
        """Most recent ``limit`` bars, returned in chronological order for charting."""
        stmt = (
            select(BarRow)
            .where(BarRow.mode == mode, BarRow.symbol == symbol, BarRow.timeframe == timeframe)
            .order_by(BarRow.ts.desc())
            .limit(limit)
        )
        rows = list((await self.s.execute(stmt)).scalars().all())
        return list(reversed(rows))

    async def add_order(self, row: OrderRow) -> None:
        self.s.add(row)
        await self.s.commit()

    async def record_equity(self, row: EquityRow) -> None:
        self.s.add(row)
        await self.s.commit()
