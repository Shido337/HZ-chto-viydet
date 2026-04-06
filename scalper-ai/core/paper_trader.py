from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from core.signal_generator import Direction, PendingOrder, Position, SetupType, Signal
from data.cache import AdaptiveParams, MarketCache

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
MAX_HOLD_EM = 6               # EM is momentum — must fire quickly or bail
MAX_HOLD_MR = 8               # MR sweep fade — medium window
MAX_HOLD_WB = 4               # WB wall edge is short-lived — exit fast
STALE_EXIT_MINUTES = 4        # early exit for deep losers (>0.5% drawdown)
STALE_EXIT_DRAWDOWN = 0.005   # 0.5% unrealized loss threshold for stale exit
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.003  # 0.3% min profit for CVD exit
CVD_EXIT_MIN_ATR_MULT = 0.5   # OR 0.5× ATR profit for CVD exit
CVD_EXIT_MIN_HOLD_SEC = 120   # hold at least 2 min before CVD exit
# Binance futures fees: maker 0.02%, taker 0.04%
MAKER_FEE = 0.0002  # limit orders (entry, TP)
TAKER_FEE = 0.0004  # market orders (SL by mark price, CVD exit, time stop)
PENDING_TIMEOUT = 60  # seconds — give pullback entries more time to fill
PENDING_WB_TIMEOUT = 30  # WB bounce limit: wall edge is short-lived, cancel sooner
WALL_MISS_GRACE = 10  # cancel pending after N consecutive wall-miss checks (10 x 100ms = 1s)


class PaperTrader:
    """Simulates fills and position lifecycle in paper mode."""

    def __init__(self, cache: MarketCache) -> None:
        self.cache = cache
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, PendingOrder] = {}
        self._wall_miss: dict[str, int] = {}  # symbol → consecutive wall-miss count for pending

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
            or (signal.setup_type == SetupType.WALL_BOUNCE and signal.wall_ref_price == 0.0)
        )

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

        notional = size_usdt
        margin = notional / LEVERAGE
        sl_pct = abs(entry - sl) / entry if entry else 0

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
            expiry=time.time() + (
                PENDING_WB_TIMEOUT if signal.setup_type == SetupType.WALL_BOUNCE
                else PENDING_TIMEOUT
            ),
        )
        self.pending[signal.symbol] = order
        logger.info(
            f"[PAPER] Limit placed {signal.direction.value} {signal.symbol} "
            f"@ {entry:.6f} (signal: {signal.entry_price:.6f}, shift={shift:+.6f}) "
            f"SL={sl:.6f} TP={tp:.6f} "
            f"notional=${notional:.2f} margin=${margin:.2f} "
            f"sl_dist={sl_pct*100:.3f}% expires={PENDING_TIMEOUT}s",
        )
        return order

    # -- pending fills ------------------------------------------------------

    def check_pending(self) -> tuple[list[Position], list[PendingOrder]]:
        """Check pending limit orders for fills and expiry."""
        filled: list[Position] = []
        expired: list[PendingOrder] = []
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
                )
                self.positions[symbol] = pos
                del self.pending[symbol]
                self._wall_miss.pop(symbol, None)
                filled.append(pos)
                logger.info(
                    f"[PAPER] Limit FILLED {order.direction.value} {symbol} "
                    f"@ {order.entry_price:.6f}",
                )
            elif now >= order.expiry:
                del self.pending[symbol]
                self._wall_miss.pop(symbol, None)
                expired.append(order)
                timeout = PENDING_WB_TIMEOUT if order.setup_type == SetupType.WALL_BOUNCE else PENDING_TIMEOUT
                logger.info(
                    f"[PAPER] Limit EXPIRED {symbol} "
                    f"@ {order.entry_price:.6f} (not filled in {timeout}s)",
                )

            # WB bounce: cancel if wall qty dropped below 5% (spoof/pulled)
            # OR if wall is being gradually absorbed (eaten → pending fills → breakout imminent)
            elif (
                order.setup_type == SetupType.WALL_BOUNCE
                and order.signal.wall_ref_price > 0
            ):
                from data.indicators import wall_qty_at_price, wall_is_eaten, wall_absorption_pct
                snap2 = self.cache.get_snapshot(symbol)
                depth = snap2.depth_bids if order.direction == Direction.LONG else snap2.depth_asks
                wall_side = "bid" if order.direction == Direction.LONG else "ask"
                current_qty = wall_qty_at_price(depth, order.signal.wall_ref_price)
                ref_qty = order.signal.wall_ref_qty or 1.0
                wall_pulled = current_qty < ref_qty * 0.05  # spoof — wall fully removed
                being_eaten = (
                    wall_is_eaten(snap2.wall_history, order.signal.wall_ref_price, wall_side)
                    and wall_absorption_pct(snap2.wall_history, order.signal.wall_ref_price, wall_side) >= 0.30
                )  # wall is being gradually absorbed → expect breakout, not bounce
                if wall_pulled or being_eaten:
                    miss = self._wall_miss.get(symbol, 0) + 1
                    self._wall_miss[symbol] = miss
                    reason_str = "absorption" if being_eaten else "pulled"
                    if miss >= WALL_MISS_GRACE:
                        del self.pending[symbol]
                        self._wall_miss.pop(symbol, None)
                        expired.append(order)
                        logger.info(
                            f"[PAPER] WB CANCELLED {symbol} "
                            f"wall {order.signal.wall_ref_price:.6f} "
                            f"qty {current_qty:.0f}/{ref_qty:.0f} "
                            f"({miss} consecutive misses, {reason_str})",
                        )
                else:
                    self._wall_miss.pop(symbol, None)

        return filled, expired

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
            self._check_breakeven(pos, snap.price, ap)
            self._check_trailing(pos, snap.price, ap)
            exit_result = self._check_exits(pos, snap)
            # WB bounce: if wall is NOW being gradually absorbed, bounce thesis flipped.
            # Close the bounce position — on the next tick absorption signal fires (market entry).
            if (
                exit_result is None
                and pos.setup_type == SetupType.WALL_BOUNCE
                and pos.signal.wall_ref_price > 0
                and (time.time() - pos.opened_at) >= 3  # min hold to avoid immediate flip
            ):
                from data.indicators import wall_is_eaten, wall_absorption_pct
                wall_side = "bid" if pos.direction == Direction.LONG else "ask"
                wp = pos.signal.wall_ref_price
                being_eaten = (
                    wall_is_eaten(snap.wall_history, wp, wall_side)
                    and wall_absorption_pct(snap.wall_history, wp, wall_side) >= 0.30
                )
                if being_eaten:
                    exit_result = ("wall_absorption_flip", snap.price)
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
    def _check_breakeven(pos: Position, price: float, ap: AdaptiveParams) -> None:
        if pos.breakeven_moved:
            return
        atr_val = ap.atr_value
        if atr_val > 0:
            trigger = atr_val * ap.breakeven_trigger_atr
        else:
            risk = pos.original_risk or abs(pos.entry_price - pos.sl_price)
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
        if is_long and price <= pos.sl_price:
            return ("sl_hit", pos.sl_price)
        if not is_long and price >= pos.sl_price:
            return ("sl_hit", pos.sl_price)
        # TP hit — fill at TP level, not market
        if is_long and price >= pos.tp_price:
            return ("tp_hit", pos.tp_price)
        if not is_long and price <= pos.tp_price:
            return ("tp_hit", pos.tp_price)
        # WB bounce: wall_absorbed exit handled in update_positions (checks live qty via wall_qty_at_price)
        # Stale exit: losing >0.5% after 4 min — cut deep losers early
        if not in_profit and elapsed_min >= STALE_EXIT_MINUTES:
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
        is_market_entry = (
            pos.setup_type == SetupType.EARLY_MOMENTUM
            or (pos.setup_type == SetupType.WALL_BOUNCE and pos.signal.wall_ref_price == 0.0)
        )
        entry_fee = pos.size_usdt * (TAKER_FEE if is_market_entry else MAKER_FEE)
        # Exit: TP = limit (maker), rest = market (taker)
        if reason == "tp_hit":
            exit_fee = pos.size_usdt * MAKER_FEE
        else:
            # sl_hit (stop-market by mark price), cvd_divergence, time_stop
            exit_fee = pos.size_usdt * TAKER_FEE
        return pnl - entry_fee - exit_fee
