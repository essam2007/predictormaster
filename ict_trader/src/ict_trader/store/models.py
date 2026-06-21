"""ORM models. Indexed columns mirror the analysis buckets; a JSON column keeps the full
detector/setup payload so nothing is lost for later mining."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BarRow(Base):
    """OHLC bars, carried in on the TradingView webhook (or seeded) so the deck can draw
    real candlestick charts and run detectors over a trade's window. One row per closed bar;
    the natural key (mode, symbol, timeframe, ts) is unique so re-sends are idempotent."""

    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("mode", "symbol", "timeframe", "ts", name="uq_bar_natural_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), index=True, default="demo")
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True, default="5")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="pine")


class SetupRow(Base):
    __tablename__ = "setups"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True, default="backtest")
    bias: Mapped[str] = mapped_column(String(8))
    fvg_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    smt1_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    smt2_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    psp_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    ltf_trigger_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    lrlr_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    timing_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    dayfilter_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    management_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_extreme_in: Mapped[bool] = mapped_column(Boolean, default=False)
    path_clean: Mapped[bool] = mapped_column(Boolean, default=False)
    killzone: Mapped[str] = mapped_column(String(16), default="none")
    quarter_idx: Mapped[int] = mapped_column(Integer, default=-1)
    amd_phase: Mapped[str] = mapped_column(String(16), default="unknown")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    gated_pass: Mapped[bool] = mapped_column(Boolean, index=True, default=False)
    entry_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    runner_target_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_risk_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    components: Mapped[dict] = mapped_column(JSON, default=dict)


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), index=True, default="backtest")
    symbol: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(8))
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_px: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_initial: Mapped[int] = mapped_column(Integer, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_r: Mapped[float] = mapped_column(Float, default=0.0)
    mae_r: Mapped[float] = mapped_column(Float, default=0.0)
    mfe_r: Mapped[float] = mapped_column(Float, default=0.0)
    day_of_week: Mapped[int] = mapped_column(Integer, default=-1, index=True)
    killzone: Mapped[str] = mapped_column(String(16), default="none", index=True)
    quarter_idx: Mapped[int] = mapped_column(Integer, default=-1)
    amd_phase: Mapped[str] = mapped_column(String(16), default="unknown")
    daily_extreme_in: Mapped[bool] = mapped_column(Boolean, default=False)
    path_clean: Mapped[bool] = mapped_column(Boolean, default=False)
    moved_to_be_early: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    be_trigger: Mapped[str] = mapped_column(String(24), default="none")
    partials_taken: Mapped[int] = mapped_column(Integer, default=0)
    runner_held: Mapped[bool] = mapped_column(Boolean, default=False)
    runner_hit_erl: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    setup_score: Mapped[float] = mapped_column(Float, default=0.0)
    events: Mapped[list] = mapped_column(JSON, default=list)


class TradeAnalysisRow(Base):
    """Auto-detected setup elements + grade for a logged trade (the 'AI detector' output).

    ``elements`` is the full detector breakdown (jsonb); the deterministic ``score``/``grade``
    come from the ICT detectors run over the trade's bar window. The ``llm_*`` columns hold an
    optional Claude narrative grade (Phase E) layered on top."""

    __tablename__ = "trade_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True, default="demo")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    grade: Mapped[str] = mapped_column(String(2), default="D")
    summary: Mapped[str] = mapped_column(String(1000), default="")
    elements: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(32), default="detectors-v1")
    llm_grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    llm_rationale: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class WebhookAlertRow(Base):
    __tablename__ = "webhook_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(16), default="pine")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)


class EquityRow(Base):
    __tablename__ = "equity"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    closed_pnl_day: Mapped[float] = mapped_column(Float, default=0.0)
    r_today: Mapped[float] = mapped_column(Float, default=0.0)
    n_trades_day: Mapped[int] = mapped_column(Integer, default=0)
