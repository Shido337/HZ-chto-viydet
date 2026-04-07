from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class SetupType(str, Enum):
    CONTINUATION_BREAK = "CONTINUATION_BREAK"
    MEAN_REVERSION = "MEAN_REVERSION"
    EARLY_MOMENTUM = "EARLY_MOMENTUM"
    WALL_BOUNCE = "WALL_BOUNCE"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class ScoreComponents:
    cvd_alignment: float = 0.0
    ob_imbalance: float = 0.0
    volume_confirmation: float = 0.0
    structure_quality: float = 0.0
    regime_match: float = 0.0
    ml_boost: float = 0.0

    def total(self) -> float:
        return (
            max(0.0, min(self.cvd_alignment, 0.25))
            + max(0.0, min(self.ob_imbalance, 0.20))
            + max(0.0, min(self.volume_confirmation, 0.15))
            + max(0.0, min(self.structure_quality, 0.15))
            + max(0.0, min(self.regime_match, 0.15))
            + max(0.0, min(self.ml_boost, 0.10))
        )


@dataclass
class Signal:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    symbol: str = ""
    direction: Direction = Direction.LONG
    setup_type: SetupType = SetupType.CONTINUATION_BREAK
    score: float = 0.0
    components: ScoreComponents = field(default_factory=ScoreComponents)
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    wall_ref_price: float = 0.0   # WB bounce only: detected wall price (limit entry + validity check)
    wall_ref_qty: float = 0.0     # WB bounce only: wall qty at signal time (for validity decay check)
    sub_setup: str = ""            # WB sub-type: "bounce" or "absorption"
    created_at: float = field(default_factory=time.time)


@dataclass
class Position:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    signal: Signal = field(default_factory=Signal)
    symbol: str = ""
    direction: Direction = Direction.LONG
    setup_type: SetupType = SetupType.CONTINUATION_BREAK
    score: float = 0.0
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    size_usdt: float = 0.0
    quantity: float = 0.0
    liquidation_price: float = 0.0
    # live order ids
    entry_order_id: int = 0
    sl_order_id: int = 0
    tp_order_id: int = 0
    trail_order_id: int = 0
    # lifecycle tracking
    opened_at: float = field(default_factory=time.time)
    best_price: float = 0.0
    original_risk: float = 0.0  # abs(entry - sl) at open, never changes
    trailing_activated: bool = False
    breakeven_moved: bool = False
    current_pnl: float = 0.0
    exit_price: float = 0.0
    # entry market state (captured at open for later analysis)
    entry_cvd_20s: float = 0.0
    entry_cvd_1m: float = 0.0
    entry_adx: float = 0.0
    entry_ob: float = 0.0       # order book imbalance: ask_qty/(bid_qty+ask_qty)
    entry_regime: str = ""
    entry_sub_setup: str = ""


@dataclass
class PendingOrder:
    """Pending limit order waiting to be filled."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    signal: Signal = field(default_factory=Signal)
    symbol: str = ""
    direction: Direction = Direction.LONG
    setup_type: SetupType = SetupType.CONTINUATION_BREAK
    score: float = 0.0
    entry_price: float = 0.0  # limit price (bid for LONG, ask for SHORT)
    sl_price: float = 0.0
    tp_price: float = 0.0
    size_usdt: float = 0.0
    quantity: float = 0.0
    created_at: float = field(default_factory=time.time)
    expiry: float = 0.0
