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
# Thresholds (prompt: CONTINUATION_BREAK)
# ---------------------------------------------------------------------------
BODY_MIN_PCT = 0.0002          # 0.02% minimum body
OB_IMBALANCE_MIN = 0.55       # 55% bid or ask
VOLUME_SPIKE_MIN = 0.5        # 0.5× avg (any meaningful volume)
MOMENTUM_BARS = 2             # last 2 1m closes in direction
ENTRY_BUFFER_PCT = 0.0001     # 0.01% buffer
TP_RR = 1.5                   # 1:1.5 — realistic for 5min scalp window
SWING_LOOKBACK = 5            # 5 candles (~15 min at 3m)
CB_MIN_SCORE = 0.75           # higher threshold for CB (base is 0.65)


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
        """3m structure break with body ≥ 0.15%."""
        candles = list(snap.klines_3m)
        if len(candles) < 12:
            return None
        last = candles[-1]
        body = abs(last["c"] - last["o"])
        body_pct = body / last["o"] if last["o"] else 0.0
        if body_pct < BODY_MIN_PCT:
            return None
        swing_h = detect_swing_high(candles[:-1], SWING_LOOKBACK)
        swing_l = detect_swing_low(candles[:-1], SWING_LOOKBACK)
        if last["c"] > swing_h and last["c"] > last["o"]:
            return Direction.LONG
        if last["c"] < swing_l and last["c"] < last["o"]:
            return Direction.SHORT
        return None

    def _check_flow(self, snap: MarketSnapshot, d: Direction) -> bool:
        """CVD, OB imbalance, momentum, volume conditions."""
        # CVD expanding in direction
        if d == Direction.LONG and snap.cvd_delta_1m <= 0:
            return False
        if d == Direction.SHORT and snap.cvd_delta_1m >= 0:
            return False
        # OB imbalance
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        if d == Direction.LONG and ob < OB_IMBALANCE_MIN:
            return False
        if d == Direction.SHORT and ob > (1 - OB_IMBALANCE_MIN):
            return False
        # 1m momentum: last 3 closes in direction
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
        # Volume spike
        if volume_spike_ratio(candles_1m) < VOLUME_SPIKE_MIN:
            return False
        return True

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction, ml_boost: float,
    ) -> Signal | None:
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
        if score < CB_MIN_SCORE:
            return None

        buffer = snap.price * ENTRY_BUFFER_PCT
        # Minimum SL: max of (0.75× ATR, 0.25% of price), capped at 0.5%
        atr_floor = snap.indicators.atr * 0.75 if snap.indicators.atr else 0
        pct_floor = snap.price * 0.0025  # absolute 0.25% minimum
        max_sl_dist = snap.price * 0.005  # cap at 0.5%
        min_sl_dist = min(max(atr_floor, pct_floor), max_sl_dist)
        if d == Direction.LONG:
            entry = last["c"] + buffer
            raw_risk = entry - last["l"]
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            risk = min(risk, max_sl_dist)  # cap SL at 0.5%
            sl = entry - risk
        else:
            entry = last["c"] - buffer
            raw_risk = last["h"] - entry
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            risk = min(risk, max_sl_dist)  # cap SL at 0.5%
            sl = entry + risk

        if risk <= 0:
            return None
        tp = entry + risk * TP_RR if d == Direction.LONG else entry - risk * TP_RR

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
