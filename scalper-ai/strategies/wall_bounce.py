"""WallBounce — Strategy 4.

Two sub-setups, mutually exclusive (absorption tried first):

  BOUNCE     Price approaching wall from safe side.
             Entry: limit order just in front of the wall (maker / GTX).
             Thesis: wall holds → price reverses.
             Filters: spoof detection + wall stable ≥5 s + ≥1 level touch
                      + VEI < 1.5.
             NOTE: CVD/OB are NOT required — bounce momentum starts FROM
             the wall, not before it. Score is based on wall quality:
             proximity (closer = better) + level touches + wall age.

  ABSORPTION Wall is actively being eaten (≥50 % absorbed in last 30 s).
             Entry: market order — window is narrow, wall won't last.
             Thesis: wall breaks → price continues through it.
             Filters: spoof detection + wall stable ≥5 s + absorption ≥30 %
                      + CVD strongly in direction.

Spoof detection: walls that flicker (appear/disappear 3+ times) or fade
in qty as price approaches (qty drops ≥25 %) are blocked.
"""
from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import (
    find_wall,
    order_book_imbalance,
    wall_absorption_pct,
    wall_stable,
    wall_is_spoof,
    count_level_touches,
    vei,
)
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
BOUNCE_DIST_PCT: float  = 0.003   # price within 0.5% of wall — tighter = better edge, smaller SL
BOUNCE_ENTRY_GAP: float = 0.0002  # limit placed 0.02 % in front of wall
BOUNCE_MIN_SCORE: float = 0.60    # lower threshold — wall quality IS the signal, not CVD/OB
ABSORPTION_PCT: float   = 0.50    # ≥50 % wall qty absorbed = active absorption (30% too early — wall still 70% alive)
MIN_CVD_BUILD: float    = 50.0    # minimum |CVD delta 20s| for absorption
WALL_MIN_SECS: float       = 10.0     # wall must be present ≥5 s (spoof filter)
MAX_ABSORPTION_DIST_PCT: float = 0.020  # wall must be within 2.0% of price for absorption
VEI_MAX_BOUNCE: float   = 1.5     # relaxed — bounce OK in moderate expansion
BOUNCE_MIN_TOUCHES: int = 1       # level touched at least once
BOUNCE_MAX_ABS_PCT: float = 0.25  # if wall already >25% absorbed → don't bounce, it's breaking
SL_BUFFER_PCT: float    = 0.0008  # 0.08 % buffer beyond wall for bounce SL
MAX_SL_PCT: float       = 0.008   # hard cap: 0.8% max risk — matches GLOBAL_MAX_SL_PCT in paper_trader
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
            ask_dist = (wp - snap.price) / snap.price if snap.price else 1.0
            if (snap.price < wp
                    and ask_dist <= MAX_ABSORPTION_DIST_PCT
                    and wall_stable(snap.wall_history, wp, "ask", WALL_MIN_SECS)
                    and not wall_is_spoof(snap.wall_history, wp, "ask")):
                # round_number NOT required — a 40%+ absorbed wall proved itself real
                abs_pct = wall_absorption_pct(snap.wall_history, wp, "ask")
                # CVD not required: absorbed wall IS the order-flow signal.
                # Only block if CVD is strongly opposing (bearish into a bull breakout).
                if abs_pct >= ABSORPTION_PCT and snap.cvd_delta_20s >= -MIN_CVD_BUILD:
                    entry = wp  # limit AT wall level — fills when price breaks through it
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
            bid_dist = (snap.price - wp) / wp if wp else 1.0
            if (snap.price > wp
                    and bid_dist <= MAX_ABSORPTION_DIST_PCT
                    and wall_stable(snap.wall_history, wp, "bid", WALL_MIN_SECS)
                    and not wall_is_spoof(snap.wall_history, wp, "bid")):
                # round_number NOT required — a 55%+ absorbed wall proved itself real
                abs_pct = wall_absorption_pct(snap.wall_history, wp, "bid")
                # CVD not required: absorbed wall IS the order-flow signal.
                # Only block if CVD is strongly opposing (bullish into a bear breakout).
                if abs_pct >= ABSORPTION_PCT and snap.cvd_delta_20s <= MIN_CVD_BUILD:
                    entry = wp  # limit AT wall level — fills when price breaks through it
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
        klines = list(snap.klines_1m)

        # VEI filter: if volatility strongly expanding, wall likely to break
        if vei(klines) > VEI_MAX_BOUNCE:
            return None

        # LONG: large bid wall below, price approaching from above → limit entry above wall
        if bid_wall:
            wp, wq = bid_wall
            dist = (snap.price - wp) / wp if wp else 1.0
            if 0 < dist <= BOUNCE_DIST_PCT:
                # Regime guard: bid walls break under strong bear trend
                if snap.regime == MarketRegime.TRENDING_BEAR:
                    return None
                # Absorption guard: if wall already being eaten → it's a breakout, not a bounce
                if wall_absorption_pct(snap.wall_history, wp, "bid", min_hist=10) >= BOUNCE_MAX_ABS_PCT:
                    return None
                touches = count_level_touches(klines, wp)
                if (wall_stable(snap.wall_history, wp, "bid", WALL_MIN_SECS)
                        and not wall_is_spoof(snap.wall_history, wp, "bid")
                        and touches >= BOUNCE_MIN_TOUCHES):
                    # If CVD is positive (buyers pushing price UP, away from wall) → market entry now.
                    # Otherwise → limit just above wall, wait for price to touch.
                    going_away = snap.cvd_delta_20s > 0
                    if going_away:
                        entry = snap.price
                    else:
                        entry = wp * (1 + BOUNCE_ENTRY_GAP)
                    sl = wp * (1 - SL_BUFFER_PCT)
                    sl_dist = (entry - sl) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = entry + (entry - sl) * ap.tp_rr
                    return self._build_bounce(
                        snap, Direction.LONG, entry, sl, tp,
                        wp, dist, touches, ap, ml_boost, going_away,
                    )

        # SHORT: large ask wall above, price approaching from below → limit entry below wall
        if ask_wall:
            wp, wq = ask_wall
            dist = (wp - snap.price) / snap.price if snap.price else 1.0
            if 0 < dist <= BOUNCE_DIST_PCT:
                # Regime guard: ask walls break under strong bull trend
                if snap.regime == MarketRegime.TRENDING_BULL:
                    return None
                # Absorption guard: if wall already being eaten → it's a breakout, not a bounce
                if wall_absorption_pct(snap.wall_history, wp, "ask", min_hist=10) >= BOUNCE_MAX_ABS_PCT:
                    return None
                touches = count_level_touches(klines, wp)
                if (wall_stable(snap.wall_history, wp, "ask", WALL_MIN_SECS)
                        and not wall_is_spoof(snap.wall_history, wp, "ask")
                        and touches >= BOUNCE_MIN_TOUCHES):
                    # If CVD is negative (sellers pushing price DOWN, away from wall) → market entry now.
                    # Otherwise → limit just below wall, wait for price to touch.
                    going_away = snap.cvd_delta_20s < 0
                    if going_away:
                        entry = snap.price
                    else:
                        entry = wp * (1 - BOUNCE_ENTRY_GAP)
                    sl = wp * (1 + SL_BUFFER_PCT)
                    sl_dist = (sl - entry) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = entry - (sl - entry) * ap.tp_rr
                    return self._build_bounce(
                        snap, Direction.SHORT, entry, sl, tp,
                        wp, dist, touches, ap, ml_boost, going_away,
                    )

        return None

    # -----------------------------------------------------------------------
    # Signal builders
    # -----------------------------------------------------------------------

    def _build_bounce(
        self,
        snap: MarketSnapshot,
        d: Direction,
        entry: float,
        sl: float,
        tp: float,
        wall_price: float,
        dist: float,
        touches: int,
        ap,
        ml_boost: float,
        is_market: bool = True,
    ) -> Signal | None:
        """Score bounce by wall quality: proximity + level age + touches.

        CVD/OB deliberately excluded — bounce momentum begins AT the wall,
        not before it.  By the time CVD aligns, the entry window has closed.
        """
        if entry <= 0 or sl <= 0 or tp <= 0:
            return None
        sl_dist = abs(entry - sl) / entry
        if sl_dist > MAX_SL_PCT:
            return None
        if d == Direction.LONG and tp <= entry:
            return None
        if d == Direction.SHORT and tp >= entry:
            return None
        if abs(tp - entry) / abs(entry - sl) < MIN_RR:
            return None

        # Proximity: closer to wall = higher conviction we're at the bounce point
        prox = max(0.0, (BOUNCE_DIST_PCT - dist) / BOUNCE_DIST_PCT)

        # Wall longevity bonus: 15 s+ = survived multiple depth updates, not a spoof
        side = "bid" if d == Direction.LONG else "ask"
        long_stable = wall_stable(snap.wall_history, wall_price, side, 15.0)

        comp = ScoreComponents(
            cvd_alignment       = prox * 0.25,                         # 0–0.25: proximity to wall
            ob_imbalance        = min(touches / 2.0, 1.0) * 0.20,     # 0–0.20: tested level
            volume_confirmation = 0.15,                                 # stable wall confirmed (required)
            structure_quality   = 0.13 if long_stable else 0.08,       # 0.08–0.13: wall longevity
            regime_match        = 0.15,                                 # bounce valid in all regimes
            ml_boost            = min(ml_boost * 0.10, 0.10),
        )
        score = self.score_components(comp)
        if score < BOUNCE_MIN_SCORE:
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
            sub_setup="bounce_market" if is_market else "bounce_limit",
        )

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
        # Use 20s CVD for scoring — reflects current momentum, not stale 1m data
        if mode == "absorption":
            cvd_raw = min(abs(snap.cvd_delta_20s) / 1000, 1.0)
        else:
            cvd_raw = min(abs(snap.cvd_delta_20s) / 500, 0.5)
        cvd_score = cvd_raw * 0.25

        ob_directional = ob if d == Direction.LONG else (1.0 - ob)
        ob_score = ob_directional * 0.20

        vol_score = 0.10 if mode == "absorption" else 0.07

        # Structure: absorbed fraction is a proxy for "how real" the signal is
        structure_score = min(abs_pct + 0.30, 1.0) * 0.15 if mode == "absorption" else 0.10

        if mode == "absorption":
            regime_ok = snap.regime in (
                MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR,
                MarketRegime.HIGH_VOL,
            )
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
            sub_setup=mode,
        )
