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
from data.indicators import find_wall, order_book_imbalance, wall_absorption_pct, wall_is_eaten, wall_stable
from core.signal_generator import Direction, ScoreComponents, SetupType, Signal
from strategies.base_strategy import BaseStrategy

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
BOUNCE_DIST_PCT: float = 0.008    # price within 0.8 % of wall (max proximity)
MIN_BOUNCE_DIST_PCT: float = 0.0002  # wall must be ≥0.02 % from price (tiny buffer vs rounding)
ABSORPTION_PCT: float = 0.30      # ≥30 % wall qty eaten (+ wall_is_eaten + price past wall)
MIN_CVD_BUILD: float = 500.0      # minimum |CVD delta 1m| for absorption (prev 150)
SL_BUFFER_PCT: float = 0.002      # 0.2 % buffer beyond wall for bounce SL
ENTRY_BEFORE_WALL_PCT: float = 0.0005  # limit 0.05 % before wall (fills sooner)
MAX_SL_PCT: float = 0.008         # hard cap: never risk more than 0.8 %
MIN_RR: float = 1.5               # minimum reward-to-risk ratio
WB_MIN_SCORE: float = 0.70        # absorption threshold (higher conviction)
BOUNCE_MIN_SCORE: float = 0.55    # bounce threshold (wall is primary thesis)


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

        # LONG: ask wall being gradually eaten by buyers.
        # Entry is BEFORE price breaks through — anticipate the breakout.
        # Price must still be BELOW (approaching) the wall so we can get a good fill.
        if ask_wall:
            wp, wq = ask_wall
            dist_to_wall = (wp - snap.price) / snap.price if snap.price else 1.0
            abs_pct = wall_absorption_pct(snap.wall_history, wp, "ask")
            if (
                abs_pct >= ABSORPTION_PCT
                and snap.cvd_delta_1m >= MIN_CVD_BUILD
                and dist_to_wall <= BOUNCE_DIST_PCT  # price is close but not past wall yet
                and wall_is_eaten(snap.wall_history, wp, "ask")  # gradual eating, not spoof
            ):
                entry = snap.ask  # market entry — breakout is imminent
                atr = ap.atr_value
                # SL: ATR-based with minimum 0.3% from entry.
                # Wall-level SL (wp*0.998) is too tight when entry < wall.
                min_sl_dist = max(atr * 0.75, entry * 0.003) if atr > 0 else entry * 0.003
                sl = entry - min_sl_dist
                sl = max(sl, entry * (1 - MAX_SL_PCT))
                sl_dist = (entry - sl) / entry
                if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                    return None
                tp = entry + atr * 2.0 if atr > 0 else entry + (entry - sl) * MIN_RR
                if tp <= entry:
                    tp = entry + (entry - sl) * MIN_RR
                return self._build(
                    snap, Direction.LONG, entry, sl, tp,
                    ob, abs_pct, "absorption", ap, ml_boost, wq,
                )

        # SHORT: bid wall being gradually eaten by sellers.
        # Entry BEFORE price breaks down — anticipate the breakdown.
        if bid_wall:
            wp, wq = bid_wall
            dist_to_wall = (snap.price - wp) / wp if wp else 1.0
            abs_pct = wall_absorption_pct(snap.wall_history, wp, "bid")
            if (
                abs_pct >= ABSORPTION_PCT
                and snap.cvd_delta_1m <= -MIN_CVD_BUILD
                and dist_to_wall <= BOUNCE_DIST_PCT  # price close but not past wall yet
                and wall_is_eaten(snap.wall_history, wp, "bid")  # gradual eating, not spoof
            ):
                entry = snap.bid
                atr = ap.atr_value
                # SL: ATR-based with minimum 0.3% from entry.
                min_sl_dist = max(atr * 0.75, entry * 0.003) if atr > 0 else entry * 0.003
                sl = entry + min_sl_dist
                sl = min(sl, entry * (1 + MAX_SL_PCT))
                sl_dist = (sl - entry) / entry
                if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                    return None
                tp = entry - atr * 2.0 if atr > 0 else entry - (sl - entry) * MIN_RR
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
        # Find walls in depth levels — MIN_BOUNCE_DIST_PCT filters spread noise
        bid_wall = find_wall(snap.depth_bids)
        ask_wall = find_wall(snap.depth_asks)

        ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)

        # LONG: large bid wall below, price approaching from above → expect bounce
        if bid_wall:
            wp, wq = bid_wall
            dist = (snap.price - wp) / wp if wp else 1.0
            if (
                MIN_BOUNCE_DIST_PCT <= dist <= BOUNCE_DIST_PCT
                and ob >= 0.45
                and wall_stable(snap.wall_history, wp, "bid")
            ):
                # Wall is the thesis — CVD direction handled by scoring, not hard gate.
                # Limit entry slightly ABOVE the wall — fills as price approaches.
                # If wall gets eaten → paper_trader closes and absorption re-enters.
                entry = wp * (1 + ENTRY_BEFORE_WALL_PCT)
                sl = wp * (1 - SL_BUFFER_PCT)
                sl_dist = (entry - sl) / entry
                if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                    return None
                tp = entry + (entry - sl) * ap.tp_rr
                return self._build(
                    snap, Direction.LONG, entry, sl, tp,
                    ob, 0.0, "bounce", ap, ml_boost, wq,
                    wall_ref_price=wp,
                )

        # SHORT: large ask wall above, price approaching from below → expect bounce down
        if ask_wall:
            wp, wq = ask_wall
            dist = (wp - snap.price) / snap.price if snap.price else 1.0
            if (
                MIN_BOUNCE_DIST_PCT <= dist <= BOUNCE_DIST_PCT
                and ob <= 0.55
                and wall_stable(snap.wall_history, wp, "ask")
            ):
                entry = wp * (1 - ENTRY_BEFORE_WALL_PCT)
                sl = wp * (1 + SL_BUFFER_PCT)
                sl_dist = (sl - entry) / entry
                if sl_dist <= 0 or sl_dist > MAX_SL_PCT:
                    return None
                tp = entry - (sl - entry) * ap.tp_rr
                return self._build(
                    snap, Direction.SHORT, entry, sl, tp,
                    ob, 0.0, "bounce", ap, ml_boost, wq,
                    wall_ref_price=wp,
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
        wall_ref_price: float = 0.0,  # bounce: wall level for limit entry + validity
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
        if mode == "absorption":
            # Absorption: CVD alignment is primary evidence
            cvd_raw = min(abs(snap.cvd_delta_1m) / 1000, 1.0)
            cvd_score = cvd_raw * 0.25
        else:
            # Bounce: wall is the thesis. CVD direction is a bonus, not the driver.
            # Base 0.15 for confirmed wall. Aligned CVD adds up to 0.10, against adds 0.05.
            cvd_mag = min(abs(snap.cvd_delta_1m) / 1000, 1.0)
            cvd_aligned = (snap.cvd_delta_1m >= 0) == (d == Direction.LONG)
            cvd_score = 0.15 + cvd_mag * (0.10 if cvd_aligned else 0.05)

        ob_directional = ob if d == Direction.LONG else (1.0 - ob)
        ob_score = ob_directional * 0.20

        vol_score = 0.10

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
        min_score = WB_MIN_SCORE if mode == "absorption" else BOUNCE_MIN_SCORE
        if score < min_score:
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
            wall_ref_price=wall_ref_price,
            wall_ref_qty=wall_qty,
        )
