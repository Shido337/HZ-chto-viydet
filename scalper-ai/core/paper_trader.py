from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from core.signal_generator import Direction, PendingOrder, Position, Signal
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
MAX_HOLD_MINUTES = 5          # SCALPING: 5 min max, no lingering
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.001  # 0.1% profit enough for CVD exit
# Binance futures fees: maker 0.02%, taker 0.04%
MAKER_FEE = 0.0002  # limit orders (entry, TP)
TAKER_FEE = 0.0004  # market orders (SL by mark price, CVD exit, time stop)
PENDING_TIMEOUT = 30  # seconds — cancel unfilled limit after this


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
        """Place a limit order at best bid/ask. Returns PendingOrder."""
        # Sanity: TP must be on the correct side of entry
        if signal.direction == Direction.LONG and signal.tp_price <= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} <= entry {signal.entry_price}")
            return None
        if signal.direction == Direction.SHORT and signal.tp_price >= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} >= entry {signal.entry_price}")
            return None

        # Use order book for better entry: bid for LONG, ask for SHORT
        snap = self.cache.get_snapshot(signal.symbol)
        if signal.direction == Direction.LONG:
            entry = snap.bid if snap.bid > 0 else signal.entry_price
        else:
            entry = snap.ask if snap.ask > 0 else signal.entry_price

        # Shift SL/TP by the same delta so risk/reward stays proportional
        shift = entry - signal.entry_price
        sl = signal.sl_price + shift
        tp = signal.tp_price + shift

        notional = size_usdt
        margin = notional / LEVERAGE

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
            expiry=time.time() + PENDING_TIMEOUT,
        )
        self.pending[signal.symbol] = order
        sl_pct = abs(entry - sl) / entry if entry else 0
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
                    f"@ {order.entry_price:.6f} (not filled in {PENDING_TIMEOUT}s)",
                )

        return filled, expired

    # -- close --------------------------------------------------------------

    def close_position(
        self, symbol: str, price: float, reason: str,
    ) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
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
            reason = self._check_exits(pos, snap)
            if reason:
                p = self.close_position(symbol, snap.price, reason)
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
    def _check_exits(pos: Position, snap: MarketSnapshot) -> str | None:
        price = snap.price
        # SL hit
        if pos.direction == Direction.LONG and price <= pos.sl_price:
            return "sl_hit"
        if pos.direction == Direction.SHORT and price >= pos.sl_price:
            return "sl_hit"
        # TP hit
        if pos.direction == Direction.LONG and price >= pos.tp_price:
            return "tp_hit"
        if pos.direction == Direction.SHORT and price <= pos.tp_price:
            return "tp_hit"
        # CVD divergence exit (only if min profit threshold met)
        pnl_pct = abs(price - pos.entry_price) / pos.entry_price if pos.entry_price else 0
        if pos.direction == Direction.LONG and snap.cvd_delta_1m < 0:
            if price > pos.entry_price and pnl_pct >= CVD_EXIT_MIN_PNL_PCT:
                return "cvd_divergence"
        if pos.direction == Direction.SHORT and snap.cvd_delta_1m > 0:
            if price < pos.entry_price and pnl_pct >= CVD_EXIT_MIN_PNL_PCT:
                return "cvd_divergence"
        # Time stop
        elapsed = (time.time() - pos.opened_at) / 60
        if elapsed >= MAX_HOLD_MINUTES:
            return "time_stop"
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
        # Entry: always limit (maker)
        entry_fee = pos.size_usdt * MAKER_FEE
        # Exit: TP = limit (maker), rest = market (taker)
        if reason == "tp_hit":
            exit_fee = pos.size_usdt * MAKER_FEE
        else:
            # sl_hit (stop-market by mark price), cvd_divergence, time_stop
            exit_fee = pos.size_usdt * TAKER_FEE
        return pnl - entry_fee - exit_fee
