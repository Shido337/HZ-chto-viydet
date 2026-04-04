from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import (
    atr_percentile as calc_atr_pct,
    detect_swing_high,
    detect_swing_low,
    order_book_imbalance,
)
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy, MIN_SCORE

# ---------------------------------------------------------------------------
# Thresholds (prompt: EARLY_MOMENTUM)
# ---------------------------------------------------------------------------
ADX_LOW = 18.0
ADX_HIGH = 30.0
ATR_COMPRESSION_PCT = 55.0   # bottom 55th percentile
CVD_CONSECUTIVE_BARS = 3     # 3+ bars building (was 1 — too noisy)
OB_CONSISTENT_MIN = 0.58     # 58%+ one side (was 0.52 — too loose)
PRICE_NEAR_LEVEL_PCT = 0.010 # 1.0% of level (tighter for scalping)
TP_FIBO = 1.618            # 1.618 fibo — realistic for scalp
MIN_RR = 1.0              # minimum 1:1 reward/risk (scalping)
TREND_EMA_BARS = 20        # 5m EMA for trend alignment


class EarlyMomentum(BaseStrategy):
    """Setup Type 3 — breakout anticipation in TRANSITIONING regime."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        # Regime: TRANSITIONING = ADX 20-25
        adx_val = snap.indicators.adx
        if not (ADX_LOW <= adx_val <= ADX_HIGH):
            return None
        if not self._check_atr_compression(snap):
            return None
        direction = self._check_cvd_buildup(snap)
        if direction is None:
            return None
        if not self._check_trend_alignment(snap, direction):
            return None
        if not self._check_ob_and_level(snap, direction):
            return None
        return self._build_signal(snap, direction, ml_boost)

    # -- sub-checks ---------------------------------------------------------

    def _check_atr_compression(self, snap: MarketSnapshot) -> bool:
        """5m ATR in bottom 20th percentile (48h window)."""
        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < 16:
            return False
        pct = calc_atr_pct(candles_5m, 14, 576)
        return pct < ATR_COMPRESSION_PCT

    def _check_cvd_buildup(self, snap: MarketSnapshot) -> Direction | None:
        """CVD building 3+ consecutive 1m bars."""
        candles_1m = list(snap.klines_1m)
        if len(candles_1m) < CVD_CONSECUTIVE_BARS + 1:
            return None
        # Approximate: check if last N candles have consistent
        # price movement direction as proxy for CVD buildup
        recent = candles_1m[-CVD_CONSECUTIVE_BARS:]
        all_up = all(c["c"] > c["o"] for c in recent)
        all_down = all(c["c"] < c["o"] for c in recent)

        if all_up and snap.cvd_delta_1m > 0:
            return Direction.LONG
        if all_down and snap.cvd_delta_1m < 0:
            return Direction.SHORT
        return None

    def _check_trend_alignment(
        self, snap: MarketSnapshot, d: Direction,
    ) -> bool:
        """5m EMA slope must agree with signal direction."""
        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < TREND_EMA_BARS + 1:
            return False
        closes = [c["c"] for c in candles_5m[-(TREND_EMA_BARS + 1):]]
        # Simple EMA approximation: compare last vs prior EMA
        mult = 2.0 / (TREND_EMA_BARS + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = c * mult + ema * (1 - mult)
        ema_prev = closes[0]
        for c in closes[1:-1]:
            ema_prev = c * mult + ema_prev * (1 - mult)
        slope = ema - ema_prev
        if d == Direction.LONG and slope <= 0:
            return False
        if d == Direction.SHORT and slope >= 0:
            return False
        return True

    def _check_ob_and_level(
        self, snap: MarketSnapshot, d: Direction,
    ) -> bool:
        """OB imbalance 65%+ and price near key level."""
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        if d == Direction.LONG and ob < OB_CONSISTENT_MIN:
            return False
        if d == Direction.SHORT and ob > (1 - OB_CONSISTENT_MIN):
            return False
        # Price near resistance (LONG) or support (SHORT)
        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < 10:
            return False
        if d == Direction.LONG:
            level = detect_swing_high(candles_5m, 10)
        else:
            level = detect_swing_low(candles_5m, 10)
        if level == 0:
            return False
        proximity = abs(snap.price - level) / level
        return proximity <= PRICE_NEAR_LEVEL_PCT

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction, ml_boost: float,
    ) -> Signal | None:
        candles_5m = list(snap.klines_5m)
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        atr_pct = calc_atr_pct(candles_5m, 14, 576)

        cvd_usd = abs(snap.cvd_delta_1m * snap.price)
        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=0.10,
            structure_quality=min((ATR_COMPRESSION_PCT - atr_pct) / 20, 1.0) * 0.15,
            regime_match=0.12,  # transitioning, not perfect match
            ml_boost=min(ml_boost, 0.10),
        )
        score = comp.total()
        if score < MIN_SCORE:
            return None

        # Compression range from 5m candles
        recent_5m = candles_5m[-10:]
        comp_high = max(c["h"] for c in recent_5m)
        comp_low = min(c["l"] for c in recent_5m)
        comp_height = comp_high - comp_low

        entry = snap.price
        # Minimum SL: max of (0.75× ATR, 0.25% of price), capped at 0.5%
        atr_floor = snap.indicators.atr * 0.75 if snap.indicators.atr else 0
        pct_floor = snap.price * 0.0025  # absolute 0.25% minimum
        max_sl_dist = snap.price * 0.005  # cap at 0.5%
        min_sl_dist = min(max(atr_floor, pct_floor), max_sl_dist)
        if d == Direction.LONG:
            raw_risk = entry - comp_low
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            risk = min(risk, max_sl_dist)  # cap SL at 0.5%
            sl = entry - risk
            raw_tp = entry + comp_height * TP_FIBO
            tp = min(raw_tp, entry + entry * 0.005)  # cap TP at 0.5%
        else:
            raw_risk = comp_high - entry
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            risk = min(risk, max_sl_dist)  # cap SL at 0.5%
            sl = entry + risk
            raw_tp = entry - comp_height * TP_FIBO
            tp = max(raw_tp, entry - entry * 0.005)  # cap TP at 0.5%

        if risk <= 0:
            return None
        # Ensure TP is on correct side and meets minimum RR
        reward = abs(tp - entry)
        if d == Direction.LONG and tp <= entry:
            return None
        if d == Direction.SHORT and tp >= entry:
            return None
        if reward / risk < MIN_RR:
            return None

        return Signal(
            symbol=snap.symbol,
            direction=d,
            setup_type=SetupType.EARLY_MOMENTUM,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
