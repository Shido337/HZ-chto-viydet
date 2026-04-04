from __future__ import annotations

from enum import Enum

from data.cache import MarketRegime
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LEVERAGE = 25
MAX_POSITION_PCT = 0.20
MAX_OPEN_POSITIONS = 5
DAILY_LOSS_LIMIT_PCT = 0.15
MAX_RISK_PER_TRADE_PCT = 0.02  # max 2% of balance at risk per trade

# Score-based multipliers (prompt spec)
SCORE_MULTIPLIERS: list[tuple[float, float, float]] = [
    (0.65, 0.72, 0.75),
    (0.73, 0.80, 1.00),
    (0.81, 0.90, 1.25),
    (0.91, 1.00, 1.50),
]


class SizeMode(str, Enum):
    FIXED = "FIXED"
    ADAPTIVE = "ADAPTIVE"
    PERCENT = "PERCENT"


class RiskManager:
    """Position sizing + risk guards."""

    def __init__(self) -> None:
        self.mode: SizeMode = SizeMode.FIXED
        self.fixed_amount: float = 50.0
        self.adaptive_base: float = 50.0
        self.percent_value: float = 5.0
        self.session_start_balance: float = 0.0
        self.daily_pnl: float = 0.0

    # -- sizing -------------------------------------------------------------

    def compute_size(
        self,
        balance: float,
        score: float,
        regime: MarketRegime,
        open_count: int,
        sl_pct: float = 0.0,
    ) -> float:
        """Returns notional USDT size or 0 if blocked by guard.

        sl_pct: stop-loss distance as fraction (e.g. 0.02 for 2%).
        When provided, caps notional so max loss ≤ 1% of balance.
        """
        if not self._check_guards(balance, open_count):
            return 0.0

        if self.mode == SizeMode.FIXED:
            base = self.fixed_amount  # FIXED = always $500, no multipliers
        elif self.mode == SizeMode.ADAPTIVE:
            base = self._adaptive_size(score, regime)
            base = self._apply_regime_mod(base, regime)
        else:
            base = balance * (self.percent_value / 100.0)
            base = self._apply_score_mult(base, score)
            base = self._apply_regime_mod(base, regime)

        cap = balance * MAX_POSITION_PCT
        size = min(base, cap)

        # Risk-cap: if SL distance known, limit notional
        # loss = sl_pct × notional (no extra leverage — notional IS leveraged)
        if sl_pct > 0:
            max_loss = balance * MAX_RISK_PER_TRADE_PCT
            risk_cap = max_loss / sl_pct
            if risk_cap < size:
                logger.info(
                    f"Risk-cap: ${size:.0f} → ${risk_cap:.0f}"
                    f" (sl={sl_pct*100:.2f}%)",
                )
                size = risk_cap
        return size

    # -- guards -------------------------------------------------------------

    def _check_guards(self, balance: float, open_count: int) -> bool:
        if open_count >= MAX_OPEN_POSITIONS:
            logger.warning("Max open positions reached")
            return False
        if self.session_start_balance > 0:
            loss_pct = -self.daily_pnl / self.session_start_balance
            if loss_pct >= DAILY_LOSS_LIMIT_PCT:
                logger.warning("Daily loss limit hit")
                return False
        return True

    def check_daily_limit(self) -> bool:
        if self.session_start_balance <= 0:
            return False
        loss_pct = -self.daily_pnl / self.session_start_balance
        return loss_pct >= DAILY_LOSS_LIMIT_PCT

    # -- helpers ------------------------------------------------------------

    def _adaptive_size(self, score: float, regime: MarketRegime) -> float:
        return self._apply_score_mult(self.adaptive_base, score)

    @staticmethod
    def _apply_score_mult(base: float, score: float) -> float:
        for lo, hi, mult in SCORE_MULTIPLIERS:
            if lo <= score <= hi:
                return base * mult
        return base * 0.75  # below min range fallback

    @staticmethod
    def _apply_regime_mod(size: float, regime: MarketRegime) -> float:
        if regime == MarketRegime.HIGH_VOL:
            return size * 0.50
        if regime == MarketRegime.LOW_VOL:
            return size * 0.75
        return size
