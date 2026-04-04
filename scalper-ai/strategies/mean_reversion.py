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
# Thresholds (prompt: MEAN_REVERSION / liquidity sweep)
# ---------------------------------------------------------------------------
SWEEP_MIN_PCT = 0.0002    # 0.02% beyond swing
SWEEP_MAX_PCT = 0.0080    # 0.80% beyond swing
OB_FLIP_MIN = 0.52        # 52% opposite after flip
VWAP_DEV_MAX = 0.020      # ±2.0% from VWAP
SL_BUFFER_PCT = 0.0005    # 0.05% beyond sweep extreme
MIN_RR = 1.0              # minimum 1:1 reward/risk (scalping)
MR_TP_RR = 1.2            # 1:1.2 — fast reversion take-profit


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
        return self._build_signal(snap, direction, ml_boost)

    # -- sub-checks ---------------------------------------------------------

    def _detect_sweep(self, snap: MarketSnapshot) -> Direction | None:
        """Detect liquidity sweep beyond swing + wick rejection."""
        candles_1m = list(snap.klines_1m)
        if len(candles_1m) < 8:
            return None
        swing_h = detect_swing_high(candles_1m[:-1], 5)
        swing_l = detect_swing_low(candles_1m[:-1], 5)
        if swing_h == 0 or swing_l == 0:
            return None

        # Check last 3 candles for sweep pattern
        for c in candles_1m[-3:]:
            # Short setup: sweep above high then close back inside
            if c["h"] > swing_h:
                sweep_pct = (c["h"] - swing_h) / swing_h
                if SWEEP_MIN_PCT <= sweep_pct <= SWEEP_MAX_PCT:
                    if c["c"] < swing_h:  # wick rejection
                        if snap.cvd_delta_1m < 0:  # CVD reversal
                            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
                            if ob < (1 - OB_FLIP_MIN):
                                return Direction.SHORT

            # Long setup: sweep below low then close back inside
            if c["l"] < swing_l:
                sweep_pct = (swing_l - c["l"]) / swing_l
                if SWEEP_MIN_PCT <= sweep_pct <= SWEEP_MAX_PCT:
                    if c["c"] > swing_l:  # wick rejection
                        if snap.cvd_delta_1m > 0:  # CVD reversal
                            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
                            if ob > OB_FLIP_MIN:
                                return Direction.LONG
        return None

    def _check_vwap(self, snap: MarketSnapshot) -> bool:
        """Price must be within ±1.5% of VWAP."""
        candles = list(snap.klines_1m)
        if not candles:
            return False
        vwap_val = calc_vwap(candles)
        if vwap_val == 0:
            return False
        dev = abs(snap.price - vwap_val) / vwap_val
        return dev <= VWAP_DEV_MAX

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction, ml_boost: float,
    ) -> Signal | None:
        candles_1m = list(snap.klines_1m)
        last = candles_1m[-1]
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        vwap_val = calc_vwap(candles_1m)

        cvd_usd = abs(snap.cvd_delta_1m * snap.price)
        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=0.10,  # sweep itself is volume event
            structure_quality=0.12,    # clean wick rejection
            regime_match=0.15,
            ml_boost=min(ml_boost, 0.10),
        )
        score = comp.total()
        if score < MIN_SCORE:
            return None

        # Minimum SL: max of (1.5× ATR, 0.5% of price)
        atr_floor = snap.indicators.atr * 1.5 if snap.indicators.atr else 0
        pct_floor = snap.price * 0.005  # absolute 0.5% minimum
        min_sl_dist = max(atr_floor, pct_floor)
        if d == Direction.LONG:
            entry = last["c"]
            raw_risk = entry - (last["l"] - last["l"] * SL_BUFFER_PCT)
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            sl = entry - risk
            tp = entry + risk * MR_TP_RR
        else:
            entry = last["c"]
            raw_risk = (last["h"] + last["h"] * SL_BUFFER_PCT) - entry
            risk = max(raw_risk, min_sl_dist) if min_sl_dist else raw_risk
            sl = entry + risk
            tp = entry - risk * MR_TP_RR

        risk = abs(entry - sl)
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
            setup_type=SetupType.MEAN_REVERSION,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
