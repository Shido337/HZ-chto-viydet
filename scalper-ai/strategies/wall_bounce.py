"""WallBounce — Strategy 4.

Detects dominant order-book walls (bid or ask levels ≥5× average depth)
and fires signals for two sub-setups:

  BOUNCE    : Price approaching the wall → expects a reversal off the wall.
              SL is placed just beyond the wall so a clean break invalidates
              the thesis immediately.

  ABSORPTION: CVD is eating the wall in real-time (≥40% of peak qty absorbed).
              Expects a break-through; SL is ATR-based on the near side.

Both sub-setups use market entry (same as EARLY_MOMENTUM) because the edge
window is narrow — walls can move or disappear quickly.

Regime: works in ALL regimes. Absorption favours trending; bounce favours
ranging/low-vol but is allowed everywhere.
"""
from __future__ import annotations

from data.cache import MarketRegime, MarketSnapshot
from data.indicators import find_wall, order_book_imbalance, wall_absorption_pct
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
BOUNCE_DIST_PCT: float = 0.008    # price within 0.8 % of wall (max proximity)
MIN_BOUNCE_DIST_PCT: float = 0.003  # wall must be ≥0.3 % from price (no spread noise)
ABSORPTION_PCT: float = 0.40      # ≥40 % wall qty absorbed = active absorption
MIN_CVD_BUILD: float = 500.0      # minimum |CVD delta 1m| for absorption (prev 150)
SL_BUFFER_PCT: float = 0.002      # 0.2 % buffer beyond wall for bounce SL
MAX_SL_PCT: float = 0.008         # hard cap: never risk more than 0.8 %
MIN_RR: float = 1.5               # minimum reward-to-risk ratio
WB_MIN_SCORE: float = 0.70        # WB-specific threshold (higher than global 0.65)


class WallBounce(BaseStrategy):
    """Order-book wall bounce / absorption strategy."""

    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        if snap.stale or not snap.price:
            return None
        if not snap.depth_bids or not snap.depth_asks:
            return None  # no depth data received yet

        bid_wall = find_wall(snap.depth_bids)
        ask_wall = find_wall(snap.depth_asks)
        if bid_wall is None and ask_wall is None:
            return None  # no significant wall on either side

        ap = snap.adaptive
        if ap.atr_value <= 0:
            return None  # ATR not yet computed — SL would be an unreliable fallback

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
            if snap.price < wp:
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
            if snap.price > wp:
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
        # For BOUNCE use depth levels 1+ (skip top-of-book = spread noise).
        # Level 0 is the best bid/ask which is always within spread distance.
        bounce_bids = snap.depth_bids[1:] if len(snap.depth_bids) > 1 else ()
        bounce_asks = snap.depth_asks[1:] if len(snap.depth_asks) > 1 else ()
        bid_wall = find_wall(bounce_bids)   # override param with spread-filtered version
        ask_wall = find_wall(bounce_asks)

        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)

        # LONG: large bid wall below, price approaching from above → expect bounce
        if bid_wall:
            wp, wq = bid_wall
            dist = (snap.price - wp) / wp if wp else 1.0
            if MIN_BOUNCE_DIST_PCT <= dist <= BOUNCE_DIST_PCT:
                if snap.cvd_delta_1m >= 0 and ob >= 0.48:
                    entry = snap.ask
                    sl = wp * (1 - SL_BUFFER_PCT)
                    sl_dist = (entry - sl) / entry
                    if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                        return None
                    tp = entry + (entry - sl) * ap.tp_rr
                    return self._build(
                        snap, Direction.LONG, entry, sl, tp,
                        ob, 0.0, "bounce", ap, ml_boost, wq,
                    )

        # SHORT: large ask wall above, price approaching from below → expect bounce down
        if ask_wall:
            wp, wq = ask_wall
            dist = (wp - snap.price) / snap.price if snap.price else 1.0
            if MIN_BOUNCE_DIST_PCT <= dist <= BOUNCE_DIST_PCT:
                if snap.cvd_delta_1m <= 0 and ob <= 0.52:
                    entry = snap.bid
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
        if score < WB_MIN_SCORE:
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
