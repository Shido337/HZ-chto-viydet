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
# Fixed structural constants (geometry, not volatility-dependent)
# ---------------------------------------------------------------------------
PRICE_NEAR_LEVEL_PCT = 0.001  # 0.10% of level — per OFCS spec: price coiling within 0.10%
CVD_BUILDUP_BARS = 3          # min consecutive 1m bars with accumulating CVD (spec: 3+)
OB_CONSISTENT_MIN = 0.65      # OB must be ≥65% consistent — per OFCS spec
MIN_RR = 0.5                  # minimum 0.5:1 — trailing compensates
TREND_EMA_BARS = 20           # 5m EMA for trend alignment
# Trending momentum (high ADX impulse entry — no ATR compression required)
TRENDING_OB_MIN = 0.55        # looser OB threshold in strong trend
TRENDING_CVD_20S_MIN = 500.0  # minimum |cvd_delta_20s| for impulse confirmation
# Adaptive entry constants come from snap.adaptive:
#   em_adx_low, em_adx_high, em_atr_compression_pct, em_cvd_bars,
#   ob_min, min_score, tp_rr, max_sl_atr, min_sl_atr, atr_value


class EarlyMomentum(BaseStrategy):
    """Setup Type 3 — breakout anticipation in TRANSITIONING regime."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        ap = snap.adaptive
        adx_val = snap.indicators.adx

        # Path 1: TRANSITIONING regime (ADX 20-25) — coiling + ATR compression
        if ap.em_adx_low <= adx_val <= ap.em_adx_high:
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

        # Path 2: TRENDING regime (ADX > em_adx_high) — impulse momentum, no ATR compression
        if adx_val > ap.em_adx_high and snap.regime in (
            MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR,
        ):
            direction = self._check_trending_impulse(snap)
            if direction is None:
                return None
            if not self._check_trend_alignment(snap, direction):
                return None
            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
            if direction == Direction.LONG and ob < TRENDING_OB_MIN:
                return None
            if direction == Direction.SHORT and ob > (1 - TRENDING_OB_MIN):
                return None
            return self._build_signal(snap, direction, ml_boost)

        return None

    # -- sub-checks ---------------------------------------------------------

    def _check_atr_compression(self, snap: MarketSnapshot) -> bool:
        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < 16:
            return False
        pct = calc_atr_pct(candles_5m, 14, 576)
        return pct < snap.adaptive.em_atr_compression_pct

    def _check_trending_impulse(self, snap: MarketSnapshot) -> Direction | None:
        """Trending regime impulse: CVD buildup + 20s delta confirms direction matches regime."""
        direction = self._check_cvd_buildup(snap)
        if direction is None:
            return None
        # Direction must align with macro regime
        if snap.regime == MarketRegime.TRENDING_BULL and direction != Direction.LONG:
            return None
        if snap.regime == MarketRegime.TRENDING_BEAR and direction != Direction.SHORT:
            return None
        # Short-term CVD impulse must confirm (real momentum, not just 3 doji candles)
        if direction == Direction.LONG and snap.cvd_delta_20s < TRENDING_CVD_20S_MIN:
            return None
        if direction == Direction.SHORT and snap.cvd_delta_20s > -TRENDING_CVD_20S_MIN:
            return None
        return direction

    def _check_cvd_buildup(self, snap: MarketSnapshot) -> Direction | None:
        """Detect CVD accumulation: 3+ consecutive 1m bars with net delta in same direction.

        Per OFCS spec: 'CVD building: net positive/negative delta accumulating
        3+ consecutive 1m bars'. This detects coiling/buildup, NOT a single impulse.
        Uses closed candles only (skip live forming [-1]).
        """
        candles_1m = list(snap.klines_1m)
        if len(candles_1m) < CVD_BUILDUP_BARS + 3:
            return None

        # Examine the last CVD_BUILDUP_BARS closed candles (skip live [-1])
        # Each candle's contribution to delta = sign of (close - open)
        closed = candles_1m[-(CVD_BUILDUP_BARS + 1):-1]  # last N closed candles

        # All must be in the same direction (consecutive accumulation)
        closes_above_opens = [c["c"] > c["o"] for c in closed]
        closes_below_opens = [c["c"] < c["o"] for c in closed]

        if all(closes_above_opens):
            # Bullish accumulation — confirm with current CVD direction
            if snap.cvd_delta_1m > 0:
                return Direction.LONG
        elif all(closes_below_opens):
            # Bearish accumulation — confirm with current CVD direction
            if snap.cvd_delta_1m < 0:
                return Direction.SHORT

        return None

    def _check_trend_alignment(
        self, snap: MarketSnapshot, d: Direction,
    ) -> bool:
        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < TREND_EMA_BARS + 1:
            return False
        closes = [c["c"] for c in candles_5m[-(TREND_EMA_BARS + 1):]]
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
        """OB must be ≥65% consistent on one side (OFCS spec: consistent 65%+ for ≥90s).
        Price must be within 0.10% of level (coiling near resistance/support).
        """
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        # Per spec: consistent bid/ask imbalance ≥65%+ on entry side
        if d == Direction.LONG and ob < OB_CONSISTENT_MIN:
            return False
        if d == Direction.SHORT and ob > (1 - OB_CONSISTENT_MIN):
            return False

        candles_5m = list(snap.klines_5m)
        if len(candles_5m) < 10:
            return False
        # LONG: price near swing LOW (support) — bounce up
        # SHORT: price near swing HIGH (resistance) — drop down
        if d == Direction.LONG:
            level = detect_swing_low(candles_5m, 10)
        else:
            level = detect_swing_high(candles_5m, 10)
        if level == 0:
            return False
        proximity = abs(snap.price - level) / level
        return proximity <= PRICE_NEAR_LEVEL_PCT

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction, ml_boost: float,
    ) -> Signal | None:
        ap = snap.adaptive
        candles_5m = list(snap.klines_5m)
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        atr_pct = calc_atr_pct(candles_5m, 14, 576)

        cvd_usd = abs(snap.cvd_delta_1m * snap.price)
        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=0.15,
            structure_quality=min((ap.em_atr_compression_pct - atr_pct) / 20, 1.0) * 0.15,
            regime_match=0.15,
            ml_boost=min(ml_boost, 0.10),
        )
        score = comp.total()
        if score < ap.min_score:
            return None

        recent_5m = candles_5m[-10:]
        comp_high = max(c["h"] for c in recent_5m)
        comp_low = min(c["l"] for c in recent_5m)

        atr_val = ap.atr_value
        if atr_val <= 0:
            return None

        entry = snap.price
        max_sl_dist = atr_val * ap.max_sl_atr
        min_sl_dist = atr_val * ap.min_sl_atr
        if d == Direction.LONG:
            raw_risk = entry - comp_low
        else:
            raw_risk = comp_high - entry

        if raw_risk > max_sl_dist:
            return None

        risk = max(raw_risk, min_sl_dist)
        if risk <= 0 or (raw_risk > 0 and risk > raw_risk * 3):
            return None
        if d == Direction.LONG:
            sl = entry - risk
            tp = entry + risk * ap.tp_rr
        else:
            sl = entry + risk
            tp = entry - risk * ap.tp_rr

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
