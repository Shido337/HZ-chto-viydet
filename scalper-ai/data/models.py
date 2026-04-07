from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TradeDirection(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, enum.Enum):
    CONTINUATION_BREAK = "CONTINUATION_BREAK"
    MEAN_REVERSION = "MEAN_REVERSION"
    EARLY_MOMENTUM = "EARLY_MOMENTUM"
    WALL_BOUNCE = "WALL_BOUNCE"


class TradeResult(str, enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(SAEnum(TradeDirection), nullable=False)
    setup_type = Column(SAEnum(SetupType), nullable=False)
    score = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=False)
    tp_price = Column(Float, nullable=True)
    size_usdt = Column(Float, nullable=False)
    pnl = Column(Float, default=0.0)
    result = Column(SAEnum(TradeResult), nullable=True)
    exit_reason = Column(String(30), nullable=True)
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    # entry market state
    entry_cvd_20s = Column(Float, nullable=True)
    entry_cvd_1m = Column(Float, nullable=True)
    entry_adx = Column(Float, nullable=True)
    entry_ob = Column(Float, nullable=True)
    entry_regime = Column(String(30), nullable=True)
    entry_sub_setup = Column(String(30), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)
    start_balance = Column(Float, nullable=False)
    end_balance = Column(Float, nullable=True)
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)


class SignalLog(Base):
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(SAEnum(TradeDirection), nullable=False)
    setup_type = Column(SAEnum(SetupType), nullable=False)
    score = Column(Float, nullable=False)
    components = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    traded = Column(Integer, default=0)  # 1 if became a trade
