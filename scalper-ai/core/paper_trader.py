from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from core.signal_generator import Direction, PendingOrder, Position, SetupType, Signal
from data.cache import AdaptiveParams, MarketCache
from data.indicators import find_wall, wall_stable

if TYPE_CHECKING:
    from data.cache import MarketSnapshot

# ---------------------------------------------------------------------------
# Constants (fallbacks — adaptive params override when available)
# ---------------------------------------------------------------------------
TRAILING_ACTIVATION_RR = 0.5  # fallback: activate trailing at 0.5× risk
TRAILING_RISK_FACTOR = 0.4    # fallback: trail distance = 40% of original risk
MIN_TRAIL_PCT = 0.0003        # absolute min trail = 0.03% of price
BREAKEVEN_TRIGGER_RR = 0.6    # fallback: BE at 0.6× risk
MAX_HOLD_MINUTES = 6          # default hard cap for losing trades that aren't moving
# Per-setup hold caps: CB needs time to consolidate at retest before continuation
MAX_HOLD_CB = 15              # CB retest can consolidate 10-15 min before breakout
MAX_HOLD_EM = 3               # EM is momentum — fire fast or bail
MAX_HOLD_MR = 6               # MR sweep fade — medium window
MAX_HOLD_WB = 3               # WB wall edge is short-lived — exit fast
STALE_EXIT_MINUTES = 2        # early exit for losers in drawdown
STALE_EXIT_DRAWDOWN = 0.003   # 0.3% unrealized loss threshold for stale exit
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.002  # 0.2% min profit for CVD exit
CVD_EXIT_MIN_ATR_MULT = 0.3   # OR 0.3× ATR profit for CVD exit (was 0.5)
CVD_EXIT_MIN_HOLD_SEC = 60    # hold at least 1 min before CVD exit (was 2 min)
# Binance futures fees: maker 0.02%, taker 0.04%
MAKER_FEE = 0.0002  # limit orders (entry, TP)
TAKER_FEE = 0.0004  # market orders (SL by mark price, CVD exit, time stop)
PENDING_TIMEOUT = 60   # seconds — default for CB / MR
PENDING_TIMEOUT_WB = 180  # WB walls can be 1-2% away; need more time to fill
GLOBAL_MAX_SL_PCT = 0.008  # 0.8% max SL distance for any trade


class PaperTrader:
    """Simulates fills and position lifecycle in paper mode."""

    def __init__(self, cache: MarketCache) -> None:
        self.cache = cache
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, PendingOrder] = {}

    @property
    def open_count(self) -> int:
        return len(self.positions) + len(self.pending)

    # -- open ---------------------------------------------------------------

    def open_position(self, signal: Signal, size_usdt: float) -> PendingOrder | None:
        """Place a limit order at best bid/ask. Returns PendingOrder.

        EARLY_MOMENTUM uses market entry (ask for LONG, bid for SHORT)
        because momentum moves away from limit orders.
        """
        # Sanity: TP must be on the correct side of entry
        if signal.direction == Direction.LONG and signal.tp_price <= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} <= entry {signal.entry_price}")
            return None
        if signal.direction == Direction.SHORT and signal.tp_price >= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} >= entry {signal.entry_price}")
            return None

        snap = self.cache.get_snapshot(signal.symbol)
        is_market = (
            signal.setup_type == SetupType.EARLY_MOMENTUM
            or (signal.setup_type == SetupType.WALL_BOUNCE and signal.sub_setup == "bounce_market")
        )  # bounce_market: CVD pushing price away from wall → fill now; bounce_limit: price heading to wall → wait

        if is_market:
            # Market entry: LONG at ask, SHORT at bid (taker)
            if signal.direction == Direction.LONG:
                entry = snap.ask if snap.ask > 0 else signal.entry_price
            else:
                entry = snap.bid if snap.bid > 0 else signal.entry_price
        else:
            # Limit entry: LONG at bid, SHORT at ask (maker)
            if signal.direction == Direction.LONG:
                entry = min(snap.bid, signal.entry_price) if snap.bid > 0 else signal.entry_price
            else:
                entry = max(snap.ask, signal.entry_price) if snap.ask > 0 else signal.entry_price

        # Shift SL/TP by the same delta so risk/reward stays proportional
        shift = entry - signal.entry_price
        sl = signal.sl_price + shift
        tp = signal.tp_price + shift

        # Global SL cap: tighten SL if risk > GLOBAL_MAX_SL_PCT of entry
        # When SL is capped, recalculate TP to maintain the strategy's intended RR
        max_sl_dist = entry * GLOBAL_MAX_SL_PCT
        sl_dist = abs(entry - sl)
        if sl_dist > max_sl_dist:
            original_rr = abs(tp - entry) / sl_dist if sl_dist > 0 else 1.5
            if signal.direction == Direction.LONG:
                sl = entry - max_sl_dist
                tp = entry + max_sl_dist * original_rr
            else:
                sl = entry + max_sl_dist
                tp = entry - max_sl_dist * original_rr

        notional = size_usdt
        margin = notional / LEVERAGE
        sl_pct = abs(entry - sl) / entry if entry else 0

        # Capture entry market state for later analysis
        total_qty = snap.bid_qty + snap.ask_qty
        entry_ob = snap.ask_qty / total_qty if total_qty > 0 else 0.5

        if is_market:
            # Immediate fill — create Position directly
            pos = Position(
                signal=signal,
                symbol=signal.symbol,
                direction=signal.direction,
                setup_type=signal.setup_type,
                score=signal.score,
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                size_usdt=notional,
                quantity=notional / entry if entry else 0,
                best_price=entry,
                original_risk=abs(entry - sl),
                entry_cvd_20s=snap.cvd_delta_20s,
                entry_cvd_1m=snap.cvd_delta_1m,
                entry_adx=snap.indicators.adx,
                entry_ob=entry_ob,
                entry_regime=snap.regime.value,
                entry_sub_setup=signal.sub_setup,
            )
            self.positions[signal.symbol] = pos
            logger.info(
                f"[PAPER] Market FILLED {signal.direction.value} {signal.symbol} "
                f"@ {entry:.6f} (signal: {signal.entry_price:.6f}, shift={shift:+.6f}) "
                f"SL={sl:.6f} TP={tp:.6f} "
                f"notional=${notional:.2f} sl_dist={sl_pct*100:.3f}%",
            )
            # Return as PendingOrder for API compat (caller expects PendingOrder|None)
            return PendingOrder(
                signal=signal, symbol=signal.symbol, direction=signal.direction,
                setup_type=signal.setup_type, score=signal.score,
                entry_price=entry, sl_price=sl, tp_price=tp,
                size_usdt=notional, quantity=notional / entry if entry else 0,
                expiry=0,
            )

        order = PendingOrder(
            signal=signal,
            symbol=signal.symbol,
            direction=signal.direction,
            setup_type=signal.setup_type,
            score=signal.score,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            size_usdt=notional,
            quantity=notional / entry if entry else 0,
            expiry=time.time() + (PENDING_TIMEOUT_WB if signal.setup_type == SetupType.WALL_BOUNCE else PENDING_TIMEOUT),
        )
        timeout_used = PENDING_TIMEOUT_WB if signal.setup_type == SetupType.WALL_BOUNCE else PENDING_TIMEOUT
        self.pending[signal.symbol] = order
        logger.info(
            f"[PAPER] Limit placed {signal.direction.value} {signal.symbol} "
            f"@ {entry:.6f} (signal: {signal.entry_price:.6f}, shift={shift:+.6f}) "
            f"SL={sl:.6f} TP={tp:.6f} "
            f"notional=${notional:.2f} margin=${margin:.2f} "
            f"sl_dist={sl_pct*100:.3f}% expires={timeout_used}s",
        )
        return order

    # -- pending fills ------------------------------------------------------

    def check_pending(self) -> tuple[list[Position], list[PendingOrder], list[PendingOrder]]:
        """Check pending limit orders for fills and expiry.

        Returns (filled, expired_timeout, wall_cancelled).
        expired_timeout: order timed out normally → ok to retry immediately.
        wall_cancelled: wall disappeared mid-wait → apply cooldown before retry.
        """
        filled: list[Position] = []
        expired: list[PendingOrder] = []
        wall_cancelled: list[PendingOrder] = []
        now = time.time()

        for symbol in list(self.pending):
            order = self.pending[symbol]
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue

            # Maker limit fill: LONG fills when ask drops to our bid,
            # SHORT fills when bid rises to our ask
            is_filled = False
            if order.direction == Direction.LONG:
                is_filled = 0 < snap.ask <= order.entry_price
            else:
                is_filled = snap.bid >= order.entry_price > 0

            if is_filled:
                total_qty = snap.bid_qty + snap.ask_qty
                fill_ob = snap.ask_qty / total_qty if total_qty > 0 else 0.5
                pos = Position(
                    signal=order.signal,
                    symbol=order.symbol,
                    direction=order.direction,
                    setup_type=order.setup_type,
                    score=order.score,
                    entry_price=order.entry_price,
                    sl_price=order.sl_price,
                    tp_price=order.tp_price,
                    size_usdt=order.size_usdt,
                    quantity=order.quantity,
                    best_price=order.entry_price,
                    original_risk=abs(order.entry_price - order.sl_price),
                    entry_cvd_20s=snap.cvd_delta_20s,
                    entry_cvd_1m=snap.cvd_delta_1m,
                    entry_adx=snap.indicators.adx,
                    entry_ob=fill_ob,
                    entry_regime=snap.regime.value,
                    entry_sub_setup=order.signal.sub_setup,
                )
                self.positions[symbol] = pos
                del self.pending[symbol]
                filled.append(pos)
                logger.info(
                    f"[PAPER] Limit FILLED {order.direction.value} {symbol} "
                    f"@ {order.entry_price:.6f}",
                )
            elif now >= order.expiry:
                del self.pending[symbol]
                expired.append(order)
                logger.info(
                    f"[PAPER] Limit EXPIRED {symbol} "
                    f"@ {order.entry_price:.6f} (not filled in {int(now - order.created_at)}s)",
                )
            elif order.setup_type == SetupType.WALL_BOUNCE:
                # Wall-gone guard: cancel WB limit if the wall we bounced off disappeared
                side = "bid" if order.direction == Direction.LONG else "ask"
                wall = find_wall(
                    snap.depth_bids if side == "bid" else snap.depth_asks,
                    mid_price=snap.price,
                )
                wall_still_there = False
                if wall:
                    wp, _ = wall
                    # Wall must be near our entry (within 1.5%) and still stable
                    wall_dist = abs(wp - order.entry_price) / order.entry_price if order.entry_price else 1.0
                    if wall_dist < 0.015 and wall_stable(snap.wall_history, wp, side, 3.0):
                        wall_still_there = True
                if not wall_still_there:
                    del self.pending[symbol]
                    wall_cancelled.append(order)
                    logger.info(
                        f"[PAPER] Limit CANCELLED {symbol} \u2014 wall gone "
                        f"(was {order.direction.value} @ {order.entry_price:.6f})",
                    )

        return filled, expired, wall_cancelled

    # -- close --------------------------------------------------------------

    def close_position(
        self, symbol: str, price: float, reason: str,
    ) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        pos.exit_price = price
        pos.current_pnl = self._calc_pnl(pos, price, reason)
        logger.info(
            f"[PAPER] Closed {symbol} @ {price:.6f} "
            f"pnl={pos.current_pnl:+.4f} reason={reason}",
        )
        return pos

    # -- update loop --------------------------------------------------------

    def update_positions(self) -> list[tuple[Position, str]]:
        """Tick all positions.  Returns list of (closed_pos, reason)."""
        closed: list[tuple[Position, str]] = []
        for symbol in list(self.positions):
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            pos = self.positions[symbol]
            ap = snap.adaptive
            self._update_price_tracking(pos, snap.price)
            # WB bounce: monitor wall absorption — exit early if wall is being eaten
            # BEFORE checking SL so we flip to breakout instead of stopping out
            if (pos.setup_type == SetupType.WALL_BOUNCE
                    and pos.signal.sub_setup.startswith("bounce")):
                early = self._check_wb_bounce_wall_absorbed(pos, snap)
                if early:
                    reason, exit_price = early
                    p = self.close_position(pos.symbol, exit_price, reason)
                    if p:
                        closed.append((p, reason))
                    continue
            # WB wall-gone guard: only for absorption — bounce SL is already tight behind wall
            if pos.setup_type == SetupType.WALL_BOUNCE and pos.signal.sub_setup == "absorption":
                self._check_wb_wall_gone(pos, snap)
            self._check_breakeven(pos, snap.price, ap)
            self._check_trailing(pos, snap.price, ap)
            exit_result = self._check_exits(pos, snap)
            if exit_result:
                reason, exit_price = exit_result
                p = self.close_position(symbol, exit_price, reason)
                if p:
                    closed.append((p, reason))
        return closed

    # -- sub-functions (≤50 lines each) -------------------------------------

    @staticmethod
    def _update_price_tracking(pos: Position, price: float) -> None:
        if pos.direction == Direction.LONG:
            pos.best_price = max(pos.best_price, price)
        else:
            pos.best_price = min(pos.best_price, price) if pos.best_price else price
        pos.current_pnl = PaperTrader._calc_pnl(pos, price)

    @staticmethod
    def _check_wb_bounce_wall_absorbed(
        pos: Position, snap: "MarketSnapshot",
    ) -> tuple[str, float] | None:
        """Early exit for WB bounce when the support/resistance wall is being eaten.

        If the wall we bounced off is now ≥30% absorbed, our thesis (wall holds)
        is invalidated.  Exit at market NOW — before price drills through SL —
        so the bot can immediately re-enter in the breakout direction.

        Returns (reason, exit_price) or None.
        """
        from data.indicators import wall_absorption_pct as _abs_pct
        ENTRY_GAP = 0.0002  # mirrors BOUNCE_ENTRY_GAP
        FLIP_THRESHOLD = 0.30  # 30% absorbed = thesis broken

        if pos.direction == Direction.LONG:
            wall_price = pos.entry_price / (1 + ENTRY_GAP)
            side = "bid"
        else:
            wall_price = pos.entry_price / (1 - ENTRY_GAP)
            side = "ask"

        abs_frac = _abs_pct(snap.wall_history, wall_price, side, min_hist=10)
        if abs_frac >= FLIP_THRESHOLD:
            logger.warning(
                f"[PAPER] WB bounce wall absorbed {abs_frac*100:.0f}% — early exit {pos.symbol} "
                f"@ {snap.price:.6f} (flip signal: {side} wall @ {wall_price:.6f})",
            )
            return ("wall_absorbed", snap.price)
        return None

    @staticmethod
    def _check_wb_wall_gone(pos: Position, snap: "MarketSnapshot") -> None:
        """If WB wall disappeared, tighten SL to just past the wall level."""
        ENTRY_GAP = 0.0002  # mirrors BOUNCE_ENTRY_GAP from wall_bounce
        TICK_BUFFER = 0.0003  # SL placed 0.03% beyond the wall level
        # Recover approximate wall price from entry
        if pos.direction == Direction.LONG:
            wall_price = pos.entry_price / (1 + ENTRY_GAP)
            side = "bid"
        else:
            wall_price = pos.entry_price / (1 - ENTRY_GAP)
            side = "ask"
        # Check if wall still exists near the original level
        book = snap.depth_bids if side == "bid" else snap.depth_asks
        wall = find_wall(book, mid_price=snap.price)
        wall_alive = False
        if wall:
            wp, _ = wall
            if abs(wp - wall_price) / wall_price < 0.003:  # within 0.3% of original wall
                wall_alive = True
        if wall_alive:
            return
        # Wall is gone — tighten SL to just past the wall level
        if pos.direction == Direction.LONG:
            new_sl = wall_price * (1 - TICK_BUFFER)
            # Only tighten, never widen (BE or trailing may have moved SL closer)
            if new_sl <= pos.sl_price:
                return
            pos.sl_price = new_sl
        else:
            new_sl = wall_price * (1 + TICK_BUFFER)
            if new_sl >= pos.sl_price:
                return
            pos.sl_price = new_sl
        logger.warning(
            "[PAPER] WB wall gone — SL tightened to {:.6f} for {} (wall was ~{:.6f})",
            new_sl, pos.symbol, wall_price,
        )

    @staticmethod
    def _check_breakeven(pos: Position, price: float, ap: AdaptiveParams) -> None:
        if pos.breakeven_moved:
            return
        risk = pos.original_risk or abs(pos.entry_price - pos.sl_price)
        # WB has very tight SL (0.08%) — ATR-based trigger is always larger than TP,
        # so use 50% of TP distance (risk * tp_rr * 0.5) for WB setups
        if pos.setup_type == SetupType.WALL_BOUNCE:
            trigger = risk * ap.tp_rr * 0.5
        else:
            atr_val = ap.atr_value
            if atr_val > 0:
                trigger = atr_val * ap.breakeven_trigger_atr
            else:
                trigger = risk * BREAKEVEN_TRIGGER_RR
        # Offset BE by round-trip fees so "breakeven" doesn't lose money
        fee_buffer = pos.entry_price * (MAKER_FEE + TAKER_FEE)
        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + trigger:
                pos.sl_price = pos.entry_price + fee_buffer
                pos.breakeven_moved = True
        else:
            if price <= pos.entry_price - trigger:
                pos.sl_price = pos.entry_price - fee_buffer
                pos.breakeven_moved = True

    @staticmethod
    def _check_trailing(pos: Position, price: float, ap: AdaptiveParams) -> None:
        atr_val = ap.atr_value
        if atr_val > 0:
            rr_trigger = atr_val * ap.trail_activation_atr
            trail_distance = max(atr_val * ap.trail_distance_atr, pos.entry_price * MIN_TRAIL_PCT)
        else:
            risk = pos.original_risk or abs(pos.entry_price - pos.sl_price)
            rr_trigger = risk * TRAILING_ACTIVATION_RR
            trail_distance = max(risk * TRAILING_RISK_FACTOR, pos.entry_price * MIN_TRAIL_PCT)
        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price - trail_distance
                if trail_sl > pos.sl_price:
                    pos.sl_price = trail_sl
        else:
            if price <= pos.entry_price - rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price + trail_distance
                if trail_sl < pos.sl_price:
                    pos.sl_price = trail_sl

    @staticmethod
    def _check_exits(
        pos: Position, snap: MarketSnapshot,
    ) -> tuple[str, float] | None:
        """Return (reason, exit_price) or None. TP/SL fill at level price."""
        price = snap.price
        elapsed_sec = time.time() - pos.opened_at
        elapsed_min = elapsed_sec / 60
        is_long = pos.direction == Direction.LONG
        in_profit = (price > pos.entry_price) if is_long else (price < pos.entry_price)
        # SL hit — fill at SL level, not market
        # WB exception: if wall is still alive at the reference level, price can't
        # physically cross it — the wall IS the stop. Don't trigger until wall is gone.
        if is_long and price <= pos.sl_price:
            if pos.setup_type == SetupType.WALL_BOUNCE:
                wall_ref = pos.signal.wall_ref_price
                if wall_ref > 0:
                    wall = find_wall(snap.depth_bids, mid_price=snap.price)
                    if wall and abs(wall[0] - wall_ref) / wall_ref < 0.003:
                        pass  # wall still there — let it absorb, no SL yet
                    else:
                        return ("sl_hit", pos.sl_price)
                else:
                    return ("sl_hit", pos.sl_price)
            else:
                return ("sl_hit", pos.sl_price)
        if not is_long and price >= pos.sl_price:
            if pos.setup_type == SetupType.WALL_BOUNCE:
                wall_ref = pos.signal.wall_ref_price
                if wall_ref > 0:
                    wall = find_wall(snap.depth_asks, mid_price=snap.price)
                    if wall and abs(wall[0] - wall_ref) / wall_ref < 0.003:
                        pass  # wall still there — let it absorb, no SL yet
                    else:
                        return ("sl_hit", pos.sl_price)
                else:
                    return ("sl_hit", pos.sl_price)
            else:
                return ("sl_hit", pos.sl_price)
        # TP hit — fill at TP level, not market
        if is_long and price >= pos.tp_price:
            return ("tp_hit", pos.tp_price)
        if not is_long and price <= pos.tp_price:
            return ("tp_hit", pos.tp_price)
        # Stale exit: losing >0.3% after 2 min — cut deep losers early (skip WB: SL is tight behind wall)
        if (not in_profit
                and elapsed_min >= STALE_EXIT_MINUTES
                and pos.setup_type != SetupType.WALL_BOUNCE):
            loss_pct = abs(price - pos.entry_price) / pos.entry_price if pos.entry_price else 0
            if loss_pct >= STALE_EXIT_DRAWDOWN:
                return ("stale_exit", price)
        # CVD divergence exit — market price
        if elapsed_sec >= CVD_EXIT_MIN_HOLD_SEC and in_profit:
            pnl_pct = abs(price - pos.entry_price) / pos.entry_price if pos.entry_price else 0
            atr_val = snap.adaptive.atr_value
            atr_profit = abs(price - pos.entry_price)
            pct_ok = pnl_pct >= CVD_EXIT_MIN_PNL_PCT
            atr_ok = atr_val <= 0 or atr_profit >= atr_val * CVD_EXIT_MIN_ATR_MULT
            if pct_ok and atr_ok:
                if is_long and snap.cvd_delta_1m < 0:
                    return ("cvd_divergence", price)
                if not is_long and snap.cvd_delta_1m > 0:
                    return ("cvd_divergence", price)
        # Time stop — only for losing positions. Winners exit via trailing/cvd/TP.
        # Per-setup hold cap: CB gets more time (retest consolidation is normal)
        if pos.setup_type == SetupType.CONTINUATION_BREAK:
            hold_cap = MAX_HOLD_CB
        elif pos.setup_type == SetupType.EARLY_MOMENTUM:
            hold_cap = MAX_HOLD_EM
        elif pos.setup_type == SetupType.WALL_BOUNCE:
            hold_cap = MAX_HOLD_WB
        else:
            hold_cap = MAX_HOLD_MR
        if not in_profit and elapsed_min >= hold_cap:
            return ("time_stop", price)
        return None

    @staticmethod
    def _calc_pnl(
        pos: Position, price: float, reason: str = "",
    ) -> float:
        # size_usdt is notional (full position), leverage already baked in
        if pos.direction == Direction.LONG:
            pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usdt
        else:
            pnl = (pos.entry_price - price) / pos.entry_price * pos.size_usdt
        # Entry: limit = maker, market (EM) = taker
        is_market_entry = pos.setup_type in (SetupType.EARLY_MOMENTUM, SetupType.WALL_BOUNCE)
        entry_fee = pos.size_usdt * (TAKER_FEE if is_market_entry else MAKER_FEE)
        # Exit: TP = limit (maker), rest = market (taker)
        if reason == "tp_hit":
            exit_fee = pos.size_usdt * MAKER_FEE
        else:
            # sl_hit (stop-market by mark price), cvd_divergence, time_stop
            exit_fee = pos.size_usdt * TAKER_FEE
        return pnl - entry_fee - exit_fee
