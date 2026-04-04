from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import (
    detect_swing_high,
    detect_swing_low,
    order_book_imbalance,
    volume_spike_ratio,
)
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy, MIN_SCORE

# ---------------------------------------------------------------------------
# Fixed structural constants (NOT volatility-dependent)
# ---------------------------------------------------------------------------
BODY_MIN_PCT = 0.0003          # 0.03% minimum body (filter noise)
MOMENTUM_BARS = 2              # last 2 1m closes in direction
ENTRY_BUFFER_PCT = 0.0001      # 0.01% buffer
SWING_LOOKBACK = 8             # 8 candles (~24 min at 3m)
MIN_RISK_PCT = 0.001           # 0.1% absolute minimum risk
MAX_RISK_PCT = 0.015           # 1.5% absolute maximum risk (scalping)
# Adaptive constants come from snap.adaptive:
#   ob_min, volume_spike_min, min_score, tp_rr,
#   max_sl_atr, min_sl_atr, atr_value


class ContinuationBreak(BaseStrategy):
    """Setup Type 1 — structure break continuation in TRENDING regime."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        # Regime: TRENDING only
        if snap.regime not in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            return None
        direction = self._detect_break(snap)
        if direction is None:
            return None
        # Continuation = WITH the trend, never against
        if snap.regime == MarketRegime.TRENDING_BULL and direction != Direction.LONG:
            return None
        if snap.regime == MarketRegime.TRENDING_BEAR and direction != Direction.SHORT:
            return None
        if not self._check_flow(snap, direction):
            return None
        return self._build_signal(snap, direction, ml_boost)

    # -- sub-checks ---------------------------------------------------------

    def _detect_break(self, snap: MarketSnapshot) -> Direction | None:
        """3m structure break with impulsive body (≥ 0.5× ATR)."""
        candles = list(snap.klines_3m)
        if len(candles) < 12:
            return None
        last = candles[-1]
        body = abs(last["c"] - last["o"])
        body_pct = body / last["o"] if last["o"] else 0.0
        if body_pct < BODY_MIN_PCT:
            return None
        # Require impulsive candle: body ≥ 0.5× ATR (confirms real break)
        atr_val = snap.adaptive.atr_value
        if atr_val > 0 and body < atr_val * 0.5:
            return None
        swing_h = detect_swing_high(candles[:-1], SWING_LOOKBACK)
        swing_l = detect_swing_low(candles[:-1], SWING_LOOKBACK)
        if last["c"] > swing_h and last["c"] > last["o"]:
            return Direction.LONG
        if last["c"] < swing_l and last["c"] < last["o"]:
            return Direction.SHORT
        return None

    def _check_flow(self, snap: MarketSnapshot, d: Direction) -> bool:
        """CVD, OB imbalance, momentum, volume — adaptive thresholds."""
        ap = snap.adaptive
        # CVD expanding in direction
        if d == Direction.LONG and snap.cvd_delta_1m <= 0:
            return False
        if d == Direction.SHORT and snap.cvd_delta_1m >= 0:
            return False
        # OB imbalance (adaptive)
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        if d == Direction.LONG and ob < ap.ob_min:
            return False
        if d == Direction.SHORT and ob > (1 - ap.ob_min):
            return False
        # 1m momentum
        candles_1m = list(snap.klines_1m)
        if len(candles_1m) < MOMENTUM_BARS + 1:
            return False
        recent = candles_1m[-MOMENTUM_BARS:]
        if d == Direction.LONG:
            if not all(c["c"] > c["o"] for c in recent):
                return False
        else:
            if not all(c["c"] < c["o"] for c in recent):
                return False
        # Volume spike (adaptive)
        if volume_spike_ratio(candles_1m) < ap.volume_spike_min:
            return False
        return True

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction, ml_boost: float,
    ) -> Signal | None:
        ap = snap.adaptive
        candles_3m = list(snap.klines_3m)
        last = candles_3m[-1]
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        vol_ratio = volume_spike_ratio(list(snap.klines_1m))

        cvd_usd = abs(snap.cvd_delta_1m * snap.price)
        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=min(vol_ratio / 3.0, 1.0) * 0.15,
            structure_quality=min(
                abs(last["c"] - last["o"]) / last["o"] / 0.003, 1.0,
            ) * 0.15,
            regime_match=0.15,
            ml_boost=min(ml_boost, 0.10),
        )
        score = comp.total()
        if score < ap.min_score:
            return None

        atr_val = ap.atr_value
        if atr_val <= 0:
            return None

        buffer = snap.price * ENTRY_BUFFER_PCT
        max_sl_dist = atr_val * ap.max_sl_atr
        min_sl_dist = atr_val * ap.min_sl_atr

        # Use pre-breakout candle for structural SL (not breakout candle)
        prev = candles_3m[-2]
        if d == Direction.LONG:
            entry = last["c"] + buffer
            raw_risk = entry - min(last["l"], prev["l"])
        else:
            entry = last["c"] - buffer
            raw_risk = max(last["h"], prev["h"]) - entry

        # Hard min/max risk bounds for scalping
        min_risk_abs = entry * MIN_RISK_PCT
        max_risk_abs = entry * MAX_RISK_PCT
        if raw_risk < min_risk_abs * 0.5:
            return None  # structure too tight — not tradeable

        # Reject if natural risk exceeds ATR cap
        if raw_risk > max_sl_dist:
            return None

        risk = max(raw_risk, min_sl_dist, min_risk_abs)
        if risk > max_risk_abs:
            return None  # too wide for scalping
        if raw_risk > 0 and risk > raw_risk * 3:
            return None  # floor inflated SL beyond structural level
        if d == Direction.LONG:
            sl = entry - risk
        else:
            sl = entry + risk
        tp = entry + risk * ap.tp_rr if d == Direction.LONG else entry - risk * ap.tp_rr

        return Signal(
            symbol=snap.symbol,
            direction=d,
            setup_type=SetupType.CONTINUATION_BREAK,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
