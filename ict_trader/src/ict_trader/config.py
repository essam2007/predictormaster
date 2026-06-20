"""Configuration: environment-driven settings with a hard demo/live interlock.

The pure detector/backtest core does not import this module, so it has no dependency on
``pydantic-settings``. The engine, execution and API layers do.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain.enums import Symbol, TradeMode

LIVE_CONFIRM_PHRASE = "I_UNDERSTAND_THE_RISK"


class InstrumentSpec:
    """Contract specs for an instrument (tick size / value / point value)."""

    def __init__(self, tick_size: float, tick_value: float) -> None:
        self.tick_size = tick_size
        self.tick_value = tick_value

    @property
    def point_value(self) -> float:
        return self.tick_value / self.tick_size


# CME E-mini contract specs.
INSTRUMENTS: dict[Symbol, InstrumentSpec] = {
    Symbol.ES: InstrumentSpec(tick_size=0.25, tick_value=12.50),  # $50/point
    Symbol.NQ: InstrumentSpec(tick_size=0.25, tick_value=5.00),  # $20/point
}


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICT_TRADER_RISK_")

    per_trade_usd: float = 250.0
    daily_loss_limit_usd: float = 750.0
    max_concurrent_positions: int = 1
    max_contracts: int = 3
    # Live mode forces size down regardless of the computed contracts.
    live_max_contracts: int = 1


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ICT_TRADER_", env_file=".env", extra="ignore"
    )

    mode: TradeMode = TradeMode.DEMO
    live_confirm: str = Field(default="", validation_alias="ICT_TRADER_LIVE_CONFIRM")
    db_url: str = "sqlite+aiosqlite:///./ict_trader.db"
    feed: str = "tradovate"  # tradovate | databento | replay

    api_host: str = "127.0.0.1"
    api_port: int = 8077
    control_token: str = ""
    webhook_secret: str = ""

    symbol_traded: Symbol = Symbol.NQ  # the instrument we route orders for

    @property
    def is_live(self) -> bool:
        return self.mode is TradeMode.LIVE

    @property
    def tradovate_base_url(self) -> str:
        return (
            "https://live.tradovateapi.com/v1"
            if self.is_live
            else "https://demo.tradovateapi.com/v1"
        )

    @property
    def tradovate_md_ws(self) -> str:
        return (
            "wss://md.tradovateapi.com/v1/websocket"
            if self.is_live
            else "wss://md-demo.tradovateapi.com/v1/websocket"
        )

    @model_validator(mode="after")
    def _check_live_interlock(self) -> Settings:
        if self.is_live and self.live_confirm != LIVE_CONFIRM_PHRASE:
            raise ValueError(
                "LIVE mode requires ICT_TRADER_LIVE_CONFIRM="
                f"{LIVE_CONFIRM_PHRASE!r}. Refusing to arm the live endpoint."
            )
        return self


class TradovateSettings(BaseSettings):
    """Tradovate API credentials, read from TRADOVATE_* env vars (see .env.example).

    Kept free of any httpx/broker import so the pure core can still import ``config``.
    """

    model_config = SettingsConfigDict(env_prefix="TRADOVATE_", env_file=".env", extra="ignore")

    name: str = ""
    password: str = ""
    app_id: str = "ict-trader"
    app_version: str = "0.1.0"
    cid: str = ""
    secret: str = ""
    device_id: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.name and self.password and self.cid and self.secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_risk_settings() -> RiskSettings:
    return RiskSettings()


@lru_cache
def get_tradovate_settings() -> TradovateSettings:
    return TradovateSettings()
