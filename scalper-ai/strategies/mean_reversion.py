from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import (
    detect_swing_high,
    detect_swing_low,
    order_book_imbalance,
    vwap as calc_vwap,
)
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy, MIN_SCORE

# ---------------------------------------------------------------------------
# Fixed structural constants (NOT volatility-dependent)
# ---------------------------------------------------------------------------
SWEEP_MIN_PCT = 0.0002    # 0.02% beyond swing
SWEEP_MAX_PCT = 0.0080    # 0.80% beyond swing
VWAP_DEV_MAX = 0.020      # ±2.0% from VWAP
SL_BUFFER_PCT = 0.0005    # 0.05% beyond sweep extreme
ENTRY_RETRACEMENT = 0.5   # enter at 50% of sweep_extreme→swing_level range
MIN_RR = 0.5              # minimum 0.5:1 — trailing compensates
# Adaptive constants come from snap.adaptive:
#   ob_min (as flip threshold), min_score, tp_rr,
#   max_sl_atr, min_sl_atr, atr_value


class MeanReversion(BaseStrategy):
    """Setup Type 2 — liquidity sweep fade in RANGING / LOW_VOL regime."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        # Regime: RANGING, LOW_VOL, or HIGH_VOL
        if snap.regime not in (
            MarketRegime.RANGING, MarketRegime.LOW_VOL, MarketRegime.HIGH_VOL,
        ):
            return None
        direction = self._detect_sweep(snap)
        if direction is None:
            return None
        if not self._check_vwap(snap):
            return None
        d, sweep_extreme, swing_level = direction
        return self._build_signal(snap, d, sweep_extreme, swing_level, ml_boost)

    # -- sub-checks ---------------------------------------------------------

    def _detect_sweep(
        self, snap: MarketSnapshot,
    ) -> tuple[Direction, float, float] | None:
        """Detect liquidity sweep. Returns (direction, sweep_extreme, swing_level)."""
        candles_1m = list(snap.klines_1m)
        if len(candles_1m) < 8:
            return None
        swing_h = detect_swing_high(candles_1m[:-1], 5)
        swing_l = detect_swing_low(candles_1m[:-1], 5)
        if swing_h == 0 or swing_l == 0:
            return None

        ob_flip = snap.adaptive.ob_min
        for c in candles_1m[-3:]:
            if c["h"] > swing_h:
                sweep_pct = (c["h"] - swing_h) / swing_h
                if SWEEP_MIN_PCT <= sweep_pct <= SWEEP_MAX_PCT:
                    if c["c"] < swing_h:
                        if snap.cvd_delta_1m < 0:
                            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
                            if ob < (1 - ob_flip):
                                return (Direction.SHORT, c["h"], swing_h)

            if c["l"] < swing_l:
                sweep_pct = (swing_l - c["l"]) / swing_l
                if SWEEP_MIN_PCT <= sweep_pct <= SWEEP_MAX_PCT:
                    if c["c"] > swing_l:
                        if snap.cvd_delta_1m > 0:
                            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
                            if ob > ob_flip:
                                return (Direction.LONG, c["l"], swing_l)
        return None

    def _check_vwap(self, snap: MarketSnapshot) -> bool:
        """Price must be within ±2% of VWAP."""
        candles = list(snap.klines_1m)
        if not candles:
            return False
        vwap_val = calc_vwap(candles)
        if vwap_val == 0:
            return False
        dev = abs(snap.price - vwap_val) / vwap_val
        return dev <= VWAP_DEV_MAX

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction,
        sweep_extreme: float, swing_level: float, ml_boost: float,
    ) -> Signal | None:
        ap = snap.adaptive
        candles_1m = list(snap.klines_1m)
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        vwap_val = calc_vwap(candles_1m)

        cvd_usd = abs(snap.cvd_delta_1m * snap.price)
        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=0.10,
            structure_quality=0.12,
            regime_match=0.15,
            ml_boost=min(ml_boost, 0.10),
        )
        score = comp.total()
        if score < ap.min_score:
            return None

        atr_val = ap.atr_value
        if atr_val <= 0:
            return None

        max_sl_dist = atr_val * ap.max_sl_atr
        # MR needs room to breathe: at least 1×ATR or 0.3% of price
        min_sl_dist = max(atr_val * 1.0, snap.price * 0.003)

        # Entry at retracement into sweep zone, SL beyond sweep extreme
        entry = swing_level + (sweep_extreme - swing_level) * ENTRY_RETRACEMENT
        if d == Direction.LONG:
            sl_raw = sweep_extreme - sweep_extreme * SL_BUFFER_PCT
            raw_risk = entry - sl_raw
        else:
            sl_raw = sweep_extreme + sweep_extreme * SL_BUFFER_PCT
            raw_risk = sl_raw - entry

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
            setup_type=SetupType.MEAN_REVERSION,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
