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
# Fixed structural constants (geometry, not volatility-dependent)
# ---------------------------------------------------------------------------
SWING_LOOKBACK = 15            # swing detection window (3m candles) — 45 min structure
BREAK_LOOKBACK = 10            # scan last 10 3m candles (~30 min) for a prior break
BODY_MIN_PCT = 0.004           # 0.4% min body on break candle — filters noise (was 0.1%)
BREAK_CLEARANCE_PCT = 0.0015   # break candle must close 0.15% beyond swing (not just a tick)
RETEST_PROXIMITY_PCT = 0.006   # price within 0.6% of level = retest zone
RETEST_OVERSHOOT_PCT = 0.002   # allow up to 0.2% past level (wick through OK)
SL_BUFFER_PCT = 0.0005         # 0.05% buffer beyond structural SL
MIN_RR = 1.5                   # minimum 1.5:1 (was 0.5 — too loose)
MAX_SL_PCT = 0.008             # 0.8% hard cap: kills catastrophic swing-to-swing SLs
# Adaptive entry constants come from snap.adaptive:
#   cb_adx_max, ob_min, volume_spike_min, min_score, tp_rr,
#   max_sl_atr, min_sl_atr, atr_value


class ContinuationBreak(BaseStrategy):
    """Setup Type 1 — break & retest continuation in TRENDING regime.

    Instead of chasing the breakout candle (old approach: entry at impulse top),
    we detect a RECENT structure break, then enter on the PULLBACK/RETEST
    of the broken level. This gives:
    - Better entry (at S/R flip level, not impulse top)
    - Tight structural SL (beyond pre-break swing)
    - Confirmed direction (break already happened)
    """

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        # Regime: TRENDING only
        if snap.regime not in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            return None
        # Skip runaway trends — very high ADX means price rarely retests cleanly
        if snap.indicators.adx > snap.adaptive.cb_adx_max:
            return None
        result = self._detect_break_and_retest(snap)
        if result is None:
            return None
        direction, broken_level, break_idx = result
        # Continuation = WITH the trend, never against
        if snap.regime == MarketRegime.TRENDING_BULL and direction != Direction.LONG:
            return None
        if snap.regime == MarketRegime.TRENDING_BEAR and direction != Direction.SHORT:
            return None
        if not self._check_flow(snap, direction):
            return None
        if not self._check_rejection_candle(snap, direction):
            return None
        return self._build_signal(snap, direction, broken_level, break_idx, ml_boost)

    # -- sub-checks ---------------------------------------------------------

    def _detect_break_and_retest(
        self, snap: MarketSnapshot,
    ) -> tuple[Direction, float, int] | None:
        """Find a recent 3m structure break and verify price is retesting.

        Returns (direction, broken_level, break_candle_index) or None.
        """
        candles = list(snap.klines_3m)
        min_candles = SWING_LOOKBACK + BREAK_LOOKBACK + 1
        if len(candles) < min_candles:
            return None

        # Swing levels from candles BEFORE the break-scan window
        prefix = candles[:-BREAK_LOOKBACK]
        swing_h = detect_swing_high(prefix, SWING_LOOKBACK)
        swing_l = detect_swing_low(prefix, SWING_LOOKBACK)
        if swing_h == 0 or swing_l == 0:
            return None

        # Scan last BREAK_LOOKBACK 3m candles for a break
        # (take the FIRST break found — the earliest, most confirmed)
        scan_start = len(candles) - BREAK_LOOKBACK
        direction: Direction | None = None
        broken_level = 0.0
        break_idx = -1

        for i in range(scan_start, len(candles)):
            c = candles[i]
            body = abs(c["c"] - c["o"])
            body_pct = body / c["o"] if c["o"] else 0.0
            if body_pct < BODY_MIN_PCT:
                continue
            if c["c"] > swing_h and c["c"] > c["o"]:
                # Must close clearly beyond swing, not just a tick above
                if (c["c"] - swing_h) / swing_h < BREAK_CLEARANCE_PCT:
                    continue
                direction = Direction.LONG
                broken_level = swing_h
                break_idx = i
                break  # take first break
            if c["c"] < swing_l and c["c"] < c["o"]:
                # Must close clearly beyond swing, not just a tick below
                if (swing_l - c["c"]) / swing_l < BREAK_CLEARANCE_PCT:
                    continue
                direction = Direction.SHORT
                broken_level = swing_l
                break_idx = i
                break

        if direction is None:
            return None

        # ---- Verify RETEST: price pulled back toward the broken level ----
        price = snap.price
        if direction == Direction.LONG:
            dist = (price - broken_level) / broken_level
            # Price should be near broken level (slight above or tiny dip below)
            if dist < -RETEST_OVERSHOOT_PCT:
                return None  # fell too far below — break failed
            if dist > RETEST_PROXIMITY_PCT:
                return None  # still too far above — no pullback yet
        else:
            dist = (broken_level - price) / broken_level
            if dist < -RETEST_OVERSHOOT_PCT:
                return None  # rose too far above — break failed
            if dist > RETEST_PROXIMITY_PCT:
                return None  # still too far below — no pullback yet

        return direction, broken_level, break_idx

    def _check_flow(self, snap: MarketSnapshot, d: Direction) -> bool:
        """OB imbalance + volume at retest level.

        CVD is intentionally NOT checked here: during a retest, price moves
        counter to the break direction (that IS the retest), so the 1m CVD
        will naturally point against the trade. The structural break already
        establishes direction. OB shows whether the level is being defended.
        """
        ap = snap.adaptive
        # OB check — loose threshold only to catch extreme mismatches:
        # During a retest the price counter-moves toward the level (low volume,
        # mixed OB). Using tight thresholds here kills every retest. We only
        # block obvious mismatches: e.g. LONG with 80% ask pressure.
        # Volume is intentionally NOT checked: retest is a low-volume pullback
        # by nature. The break candle already passed body_pct quality check.
        CB_OB_MIN = 0.35
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        if d == Direction.LONG and ob < CB_OB_MIN:
            return False
        if d == Direction.SHORT and ob > (1 - CB_OB_MIN):
            return False
        return True

    def _check_rejection_candle(self, snap: MarketSnapshot, d: Direction) -> bool:
        """Last CLOSED 1m candle must show rejection at the retest level.

        LONG retest: price should be bouncing — close in upper half of candle range.
        SHORT retest: price should be failing — close in lower half of candle range.
        Uses [-2] (closed candle), not [-1] (live forming candle), because during
        an active retest the live candle moves toward the level and closes in the
        wrong half, giving a false rejection signal.
        """
        candles = list(snap.klines_1m)
        if len(candles) < 2:
            return False
        cur = candles[-2]  # last confirmed closed candle
        h, l, c = cur["h"], cur["l"], cur["c"]
        candle_range = h - l
        if candle_range <= 0:
            return True  # degenerate candle — don't reject on zero-range
        mid = (h + l) / 2.0
        if d == Direction.LONG:
            return c >= mid   # close in upper half = bullish rejection of level
        return c <= mid       # close in lower half = bearish rejection of level

    def _build_signal(
        self, snap: MarketSnapshot, d: Direction,
        broken_level: float, break_idx: int, ml_boost: float,
    ) -> Signal | None:
        ap = snap.adaptive
        candles_3m = list(snap.klines_3m)
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        vol_ratio = volume_spike_ratio(list(snap.klines_1m))
        cvd_usd = abs(snap.cvd_delta_1m * snap.price)

        # Structure quality = how cleanly price retests (closer = better)
        dist_to_level = abs(snap.price - broken_level) / broken_level if broken_level else 1.0
        retest_quality = max(0.0, 1.0 - dist_to_level / RETEST_PROXIMITY_PCT)

        comp = ScoreComponents(
            cvd_alignment=min(cvd_usd / 5000, 1.0) * 0.25,
            ob_imbalance=(ob if d == Direction.LONG else 1 - ob) * 0.20,
            volume_confirmation=min(vol_ratio / 3.0, 1.0) * 0.15,
            structure_quality=retest_quality * 0.15,
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
        min_sl_dist = atr_val * ap.min_sl_atr

        # Entry: at the broken level (limit order on pullback retest)
        entry = broken_level

        # SL: beyond the pre-break swing structure
        pre_break = candles_3m[:break_idx]
        if len(pre_break) < 3:
            return None

        sl_lookback = min(SWING_LOOKBACK, len(pre_break))
        if d == Direction.LONG:
            struct_low = min(c["l"] for c in pre_break[-sl_lookback:])
            sl_raw = struct_low * (1 - SL_BUFFER_PCT)
            raw_risk = entry - sl_raw
        else:
            struct_high = max(c["h"] for c in pre_break[-sl_lookback:])
            sl_raw = struct_high * (1 + SL_BUFFER_PCT)
            raw_risk = sl_raw - entry

        if raw_risk <= 0:
            return None
        if raw_risk > max_sl_dist:
            return None
        # Hard cap: structural SL wider than MAX_SL_PCT is a catastrophic-loss setup
        if raw_risk / entry > MAX_SL_PCT:
            return None

        risk = max(raw_risk, min_sl_dist)
        if risk > raw_risk * 3:
            return None  # floor inflated SL beyond structural level

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
            setup_type=SetupType.CONTINUATION_BREAK,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
