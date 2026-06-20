"""Enumerations shared across the whole system.

These are deliberately plain ``str`` enums so they serialize cleanly to JSON / the DB
and read well in the research deck.
"""

from __future__ import annotations

from enum import Enum


class Side(str, Enum):
    """Trade direction / bias."""

    LONG = "long"
    SHORT = "short"
    NONE = "none"

    @property
    def opposite(self) -> Side:
        if self is Side.LONG:
            return Side.SHORT
        if self is Side.SHORT:
            return Side.LONG
        return Side.NONE


class Symbol(str, Enum):
    """The two correlated instruments. ES is the canonical lagger, NQ the leader."""

    ES = "ES"
    NQ = "NQ"


class Timeframe(str, Enum):
    """Supported bar timeframes (minutes)."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}[self.value]


class ComponentId(str, Enum):
    """The nine confluence components of the A+ setup, plus the structure helper."""

    FVG = "FVG"  # HTF fair value gap / bias
    SMT1 = "SMT1"  # stage-1 divergence
    SMT2 = "SMT2"  # stage-2 nested divergence
    PSP = "PSP"  # precision swing point
    LTF_TRIGGER = "LTF_TRIGGER"  # LTF FVG + inverse FVG
    LRLR = "LRLR"  # clean low-resistance path
    TIMING = "TIMING"  # killzone / macro / quarter / extreme-not-in
    DAYFILTER = "DAYFILTER"  # day of week / news
    MANAGEMENT = "MANAGEMENT"  # a valid management plan exists
    STRUCTURE = "STRUCTURE"  # helper (BOS/MSS/displacement), not a gate


class Killzone(str, Enum):
    NONE = "none"
    ASIA = "asia"
    LONDON = "london"
    NY_AM = "ny_am"
    SILVER_BULLET = "silver_bullet"  # 10:00-11:00 ET
    LUNCH = "lunch"
    NY_PM = "ny_pm"


class AMDPhase(str, Enum):
    """Quarterly-Theory AMD(X) phase of a 90-minute quarter."""

    ACCUMULATION = "accumulation"
    MANIPULATION = "manipulation"
    DISTRIBUTION = "distribution"
    CONTINUATION = "continuation"
    UNKNOWN = "unknown"


class PDArrayKind(str, Enum):
    FVG = "fvg"
    IFVG = "ifvg"
    ORDER_BLOCK = "order_block"
    BREAKER = "breaker"


class LiquidityKind(str, Enum):
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"
    PDH = "pdh"
    PDL = "pdl"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    TRAILING_STOP = "trailing_stop"


class OrderStatus(str, Enum):
    PENDING = "pending"
    WORKING = "working"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ExitReason(str, Enum):
    STOP = "stop"
    TP = "tp"
    RUNNER_TARGET = "runner_target"
    TRAIL = "trail"
    BREAKEVEN = "be"
    MANUAL = "manual"
    KILL_SWITCH = "kill_switch"


class BreakevenTrigger(str, Enum):
    """Why a breakeven move happened — the heart of the documented-flaw analysis."""

    NONE = "none"
    STRUCTURAL_BREAK = "structural_break"  # allowed
    DISPLACEMENT = "displacement"  # allowed
    EARLY_PULLBACK = "early_pullback"  # the flaw — should never be emitted by our logic


class TradeMode(str, Enum):
    DEMO = "demo"
    LIVE = "live"
    BACKTEST = "backtest"
