"""WallBounce — Strategy 4.

Two sub-setups, mutually exclusive (absorption tried first):

  BOUNCE     Price approaching wall from safe side.
             Entry: limit order just in front of the wall (maker / GTX).
             Thesis: wall holds → price reverses.
             Filters: round number + wall stable ≥5 s + ≥2 level touches
                      + VEI < 1.2 + CVD not opposing + OB aligned.

  ABSORPTION Wall is actively being eaten (≥40 % absorbed in last 30 s).
             Entry: market order — window is narrow, wall won't last.
             Thesis: wall breaks → price continues through it.
             Filters: round number + wall stable + absorption ≥40 %
                      + CVD strongly in direction.
             (level touches NOT required — persistent absorption already
              proves the level was real and held long enough.)

The two setups never conflict: absorption is checked first; if found, bounce
is skipped entirely.  If absorption is zero (wall intact, not being eaten),
bounce is evaluated.
"""
from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import (
    find_wall,
    order_book_imbalance,
    wall_absorption_pct,
    wall_stable,
    wall_on_round_number,
    count_level_touches,
    vei,
)
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
BOUNCE_DIST_PCT: float  = 0.003   # price within 0.3 % of wall to enter
BOUNCE_ENTRY_GAP: float = 0.0002  # limit placed 0.02 % in front of wall
ABSORPTION_PCT: float   = 0.55    # ≥55 % wall qty absorbed = active absorption
MIN_CVD_BUILD: float    = 150.0   # minimum |CVD delta 1m| for absorption
WALL_MIN_SECS: float    = 5.0     # wall must be present ≥5 s (spoof filter)
VEI_MAX_BOUNCE: float   = 1.2     # bounce skipped when ATR(10)/ATR(50) > 1.2
BOUNCE_MIN_TOUCHES: int = 2       # level must have been tested ≥2 times
SL_BUFFER_PCT: float    = 0.0008  # 0.08 % buffer beyond wall for bounce SL
MAX_SL_PCT: float       = 0.008   # hard cap: never risk more than 0.8 %
MIN_RR: float           = 1.5     # minimum reward-to-risk ratio


class WallBounce(BaseStrategy):
    """Order-book wall bounce / absorption strategy."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        if not snap.depth_bids or not snap.depth_asks:
            return None  # no depth data received yet

        mid = snap.price
        bid_wall = find_wall(snap.depth_bids, mid_price=mid)
        ask_wall = find_wall(snap.depth_asks, mid_price=mid)
        if bid_wall is None and ask_wall is None:
            return None  # no significant wall on either side

        ap = snap.adaptive

        # Absorption has higher conviction — try it first
        sig = self._check_absorption(snap, bid_wall, ask_wall, ap, ml_boost)
        if sig:
            return sig

        return self._check_bounce(snap, bid_wall, ask_wall, ap, ml_boost)

    # -----------------------------------------------------------------------
    # Sub-setup checkers
    # -----------------------------------------------------------------------

    def _check_absorption(
        self,
        snap: MarketSnapshot,
        bid_wall: tuple[float, float] | None,
        ask_wall: tuple[float, float] | None,
        ap,
        ml_boost: float,
    ) -> Signal | None:
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)

        # LONG: ask wall being absorbed by buyers (price below wall, buyers pressing up)
        if ask_wall:
            wp, wq = ask_wall
            if (snap.price < wp
                    and wall_stable(snap.wall_history, wp, "ask", WALL_MIN_SECS)):
                # round_number NOT required — a 40%+ absorbed wall proved itself real
                abs_pct = wall_absorption_pct(snap.wall_history, wp, "ask")
                if abs_pct >= ABSORPTION_PCT and snap.cvd_delta_1m >= MIN_CVD_BUILD:
                    entry = snap.ask
                    atr = ap.atr_value
                    raw_sl = entry - max(atr * 1.2, entry * 0.003) if atr > 0 else entry * (1 - 0.003)
                    sl = max(raw_sl, entry * (1 - MAX_SL_PCT))
                    sl_dist = (entry - sl) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = wp + atr * 1.5 if atr > 0 else entry + (entry - sl) * MIN_RR
                    if tp <= entry:
                        tp = entry + (entry - sl) * MIN_RR
                    return self._build(
                        snap, Direction.LONG, entry, sl, tp,
                        ob, abs_pct, "absorption", ap, ml_boost, wq,
                    )

        # SHORT: bid wall being absorbed by sellers (price above wall, sellers pressing down)
        if bid_wall:
            wp, wq = bid_wall
            if (snap.price > wp
                    and wall_stable(snap.wall_history, wp, "bid", WALL_MIN_SECS)):
                # round_number NOT required — a 40%+ absorbed wall proved itself real
                abs_pct = wall_absorption_pct(snap.wall_history, wp, "bid")
                if abs_pct >= ABSORPTION_PCT and snap.cvd_delta_1m <= -MIN_CVD_BUILD:
                    entry = snap.bid
                    atr = ap.atr_value
                    raw_sl = entry + max(atr * 1.2, entry * 0.003) if atr > 0 else entry * (1 + 0.003)
                    sl = min(raw_sl, entry * (1 + MAX_SL_PCT))
                    sl_dist = (sl - entry) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = wp - atr * 1.5 if atr > 0 else entry - (sl - entry) * MIN_RR
                    if tp >= entry:
                        tp = entry - (sl - entry) * MIN_RR
                    return self._build(
                        snap, Direction.SHORT, entry, sl, tp,
                        ob, abs_pct, "absorption", ap, ml_boost, wq,
                    )

        return None

    def _check_bounce(
        self,
        snap: MarketSnapshot,
        bid_wall: tuple[float, float] | None,
        ask_wall: tuple[float, float] | None,
        ap,
        ml_boost: float,
    ) -> Signal | None:
        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)
        klines = list(snap.klines_1m)

        # VEI filter applies to the entire bounce setup — skip if volatility expanding
        if vei(klines) > VEI_MAX_BOUNCE:
            return None

        # LONG: large bid wall below, price approaching from above → limit entry above wall
        if bid_wall:
            wp, wq = bid_wall
            dist = (snap.price - wp) / wp if wp else 1.0
            if 0 < dist <= BOUNCE_DIST_PCT:
                if (wall_on_round_number(wp)
                        and wall_stable(snap.wall_history, wp, "bid", WALL_MIN_SECS)
                        and count_level_touches(klines, wp) >= BOUNCE_MIN_TOUCHES
                        and snap.cvd_delta_1m >= 0
                        and ob >= 0.48):
                    entry = wp * (1 + BOUNCE_ENTRY_GAP)  # limit just above wall (maker)
                    sl = wp * (1 - SL_BUFFER_PCT)
                    sl_dist = (entry - sl) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = entry + (entry - sl) * ap.tp_rr
                    return self._build(
                        snap, Direction.LONG, entry, sl, tp,
                        ob, 0.0, "bounce", ap, ml_boost, wq,
                    )

        # SHORT: large ask wall above, price approaching from below → limit entry below wall
        if ask_wall:
            wp, wq = ask_wall
            dist = (wp - snap.price) / snap.price if snap.price else 1.0
            if 0 < dist <= BOUNCE_DIST_PCT:
                if (wall_on_round_number(wp)
                        and wall_stable(snap.wall_history, wp, "ask", WALL_MIN_SECS)
                        and count_level_touches(klines, wp) >= BOUNCE_MIN_TOUCHES
                        and snap.cvd_delta_1m <= 0
                        and ob <= 0.52):
                    entry = wp * (1 - BOUNCE_ENTRY_GAP)  # limit just below wall (maker)
                    sl = wp * (1 + SL_BUFFER_PCT)
                    sl_dist = (sl - entry) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = entry - (sl - entry) * ap.tp_rr
                    return self._build(
                        snap, Direction.SHORT, entry, sl, tp,
                        ob, 0.0, "bounce", ap, ml_boost, wq,
                    )

        return None

    # -----------------------------------------------------------------------
    # Signal builder
    # -----------------------------------------------------------------------

    def _build(
        self,
        snap: MarketSnapshot,
        d: Direction,
        entry: float,
        sl: float,
        tp: float,
        ob: float,
        abs_pct: float,
        mode: str,
        ap,
        ml_boost: float,
        wall_qty: float,  # noqa: ARG002  (reserved for future scaling)
    ) -> Signal | None:
        if entry <= 0 or sl <= 0 or tp <= 0:
            return None

        sl_dist = abs(entry - sl) / entry
        if sl_dist > MAX_SL_PCT:
            return None
        if d == Direction.LONG and tp <= entry:
            return None
        if d == Direction.SHORT and tp >= entry:
            return None

        rr = abs(tp - entry) / abs(entry - sl)
        if rr < MIN_RR:
            return None

        # -- Score breakdown -------------------------------------------------
        # Absorption: CVD alignment is primary evidence
        if mode == "absorption":
            cvd_raw = min(abs(snap.cvd_delta_1m) / 1000, 1.0)
        else:
            cvd_raw = min(abs(snap.cvd_delta_1m) / 500, 0.5)
        cvd_score = cvd_raw * 0.25

        ob_directional = ob if d == Direction.LONG else (1.0 - ob)
        ob_score = ob_directional * 0.20

        vol_score = 0.10 if mode == "absorption" else 0.07

        # Structure: absorbed fraction is a proxy for "how real" the signal is
        structure_score = min(abs_pct + 0.30, 1.0) * 0.15 if mode == "absorption" else 0.10

        if mode == "absorption":
            # Absorption is a with-trend play when regime strongly trending.
            # Counter-trend absorption (e.g. SHORT in TRENDING_BULL) gets no
            # regime bonus — the trend has momentum that can overwhelm a wall.
            bull_trend = snap.regime == MarketRegime.TRENDING_BULL
            bear_trend = snap.regime == MarketRegime.TRENDING_BEAR
            aligned = (
                (d == Direction.LONG and (bull_trend or snap.regime == MarketRegime.HIGH_VOL))
                or (d == Direction.SHORT and (bear_trend or snap.regime == MarketRegime.HIGH_VOL))
                or snap.regime in (MarketRegime.RANGING, MarketRegime.LOW_VOL)
            )
            # Hard block: never take absorption shorts in a strong bull trend (or vice versa)
            if (d == Direction.SHORT and bull_trend) or (d == Direction.LONG and bear_trend):
                return None
            regime_ok = aligned
        else:
            regime_ok = True  # bounce works in all regimes
        regime_score = 0.15 if regime_ok else 0.07

        comp = ScoreComponents(
            cvd_alignment=cvd_score,
            ob_imbalance=ob_score,
            volume_confirmation=vol_score,
            structure_quality=structure_score,
            regime_match=regime_score,
            ml_boost=min(ml_boost * 0.10, 0.10),
        )
        score = self.score_components(comp)
        if score < ap.min_score:
            return None

        return Signal(
            symbol=snap.symbol,
            direction=d,
            setup_type=SetupType.WALL_BOUNCE,
            score=score,
            components=comp,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
        )
