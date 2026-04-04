from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.signal_generator import Direction, Position, Signal
from data.cache import AdaptiveParams, MarketCache

if TYPE_CHECKING:
    from data.cache import MarketSnapshot
    from exchange.binance_client import BinanceClient
    from exchange.order_executor import OrderExecutor

# ---------------------------------------------------------------------------
# Constants (fallbacks -- adaptive params override when available)
# ---------------------------------------------------------------------------
TRAILING_ACTIVATION_RR = 0.5
TRAILING_RISK_FACTOR = 0.4
MIN_TRAIL_PCT = 0.0003
BREAKEVEN_TRIGGER_RR = 0.6
MAX_HOLD_MINUTES = 8
MAX_HOLD_IF_PROFIT = 12
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.003
CVD_EXIT_MIN_ATR_MULT = 0.5
CVD_EXIT_MIN_HOLD_SEC = 120
MAKER_FEE = 0.0002
TAKER_FEE = 0.0004
# Throttle: minimum seconds between exchange SL updates per symbol
SL_UPDATE_THROTTLE = 3.0


class LiveTrader:
    """Real exchange execution with full position lifecycle.

    Mirrors PaperTrader adaptive exit logic (trailing, BE, CVD exit,
    time stop) but sends real orders to Binance via OrderExecutor.

    Listens for ORDER_TRADE_UPDATE events from user data stream so
    we know when exchange-side SL/TP fires (no double-action).
    """

    def __init__(
        self,
        cache: MarketCache,
        client: BinanceClient,
        executor: OrderExecutor,
    ) -> None:
        self.cache = cache
        self.client = client
        self.executor = executor
        self.positions: dict[str, Position] = {}
        # Track last SL update time per symbol to avoid rate limiting
        self._last_sl_update: dict[str, float] = {}
        # Positions closed by exchange (SL/TP hit on Binance side)
        self._exchange_closed: dict[str, str] = {}  # symbol -> reason

    @property
    def open_count(self) -> int:
        return len(self.positions)

    # -- exchange event handler (called from user data stream) --------------

    async def on_order_update(self, data: dict[str, Any]) -> None:
        """Handle ORDER_TRADE_UPDATE from Binance user data stream.

        Detects when exchange-side SL or TP fires so we dont try to
        close the position again ourselves.
        """
        order = data.get("o", {})
        symbol = order.get("s", "")
        status = order.get("X", "")  # FILLED, PARTIALLY_FILLED, etc.
        order_type = order.get("ot", "")  # STOP_MARKET, TAKE_PROFIT_MARKET
        reduce_only = order.get("R", False)  # reduceOnly flag

        if symbol not in self.positions:
            return

        if status != "FILLED":
            return

        pos = self.positions[symbol]

        # Exchange SL fired
        if order_type == "STOP_MARKET" and reduce_only:
            realized_pnl = float(order.get("rp", 0))
            logger.info(
                f"[LIVE] Exchange SL FILLED {symbol} "
                f"realized_pnl={realized_pnl:+.4f}",
            )
            self._exchange_closed[symbol] = "sl_hit"

        # Exchange TP fired
        elif order_type == "TAKE_PROFIT_MARKET" and reduce_only:
            realized_pnl = float(order.get("rp", 0))
            logger.info(
                f"[LIVE] Exchange TP FILLED {symbol} "
                f"realized_pnl={realized_pnl:+.4f}",
            )
            self._exchange_closed[symbol] = "tp_hit"

    # -- open position ------------------------------------------------------

    async def open_position(
        self, signal: Signal, size_usdt: float,
    ) -> Position | None:
        await self.executor.prepare_symbol(signal.symbol)
        qty = self.executor.round_quantity(
            signal.symbol, size_usdt / signal.entry_price,
        ) if signal.entry_price else 0
        if qty <= 0:
            return None

        entry_price = self.executor.round_price(
            signal.symbol, signal.entry_price,
        )
        sl_price = self.executor.round_price(
            signal.symbol, signal.sl_price,
        )
        tp_price = self.executor.round_price(
            signal.symbol, signal.tp_price,
        )

        entry_resp = await self._place_entry(signal, qty, entry_price)
        if not entry_resp.get("orderId"):
            return None

        # Use actual filled quantity (may differ from requested)
        filled_qty = float(entry_resp.get("filledQty", qty))
        avg_price = float(entry_resp.get("avgPrice", entry_price))
        if filled_qty <= 0:
            return None

        pos = self._create_position(
            signal, size_usdt, filled_qty, entry_resp,
            sl_price, tp_price, avg_price,
        )
        ok = await self._place_protective_orders(pos)
        if not ok:
            await self._emergency_close(pos)
            return None

        self.positions[signal.symbol] = pos
        logger.info(
            f"[LIVE] Opened {signal.direction.value} {signal.symbol} "
            f"@ {avg_price:.6f} qty={filled_qty} size=${size_usdt:.2f} "
            f"SL={pos.sl_price:.6f} TP={pos.tp_price:.6f}",
        )
        return pos

    # -- close position -----------------------------------------------------

    async def close_position(
        self, symbol: str, reason: str,
    ) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        exchange_reason = self._exchange_closed.pop(symbol, None)
        if exchange_reason:
            # Exchange already closed this -- just clean up orders
            reason = exchange_reason
            await self.executor.cancel_all(symbol)
        else:
            # We are closing -- cancel SL/TP first (rule 10), then market close
            await self.executor.cancel_all(symbol)
            side = "SELL" if pos.direction == Direction.LONG else "BUY"
            await self.executor.market_close(symbol, side, pos.quantity)

        snap = self.cache.get_snapshot(symbol)
        pos.current_pnl = self._calc_pnl(pos, snap.price, reason)
        self._last_sl_update.pop(symbol, None)
        logger.info(
            f"[LIVE] Closed {symbol} reason={reason} "
            f"pnl={pos.current_pnl:+.4f}",
        )
        return pos

    # -- update loop --------------------------------------------------------

    async def update_positions(self) -> list[tuple[Position, str]]:
        closed: list[tuple[Position, str]] = []

        # First: process positions closed by exchange events
        for symbol in list(self._exchange_closed):
            if symbol in self.positions:
                p = await self.close_position(symbol, "exchange_event")
                if p:
                    closed.append((p, self._exchange_closed.get(symbol, "exchange_event")))

        for symbol in list(self.positions):
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            pos = self.positions[symbol]
            ap = snap.adaptive
            self._update_price_tracking(pos, snap.price)
            self._check_breakeven(pos, snap.price, ap)
            sl_changed = self._check_trailing(pos, snap.price, ap)

            # Throttled SL update on exchange
            if sl_changed:
                now = time.time()
                last = self._last_sl_update.get(symbol, 0)
                if now - last >= SL_UPDATE_THROTTLE:
                    self._last_sl_update[symbol] = now
                    await self._update_exchange_sl(pos)

            # Software exits (CVD divergence, time stop)
            # Note: SL/TP hits are handled by exchange events, not here
            reason = self._check_software_exits(pos, snap)
            if reason:
                p = await self.close_position(symbol, reason)
                if p:
                    closed.append((p, reason))
        return closed

    # -- recovery -----------------------------------------------------------

    async def recover_positions(self) -> None:
        """Restore positions from exchange state on restart."""
        exchange_pos = await self.client.get_positions()
        for ep in exchange_pos:
            symbol = ep.get("symbol", "")
            amt = float(ep.get("positionAmt", 0))
            if amt == 0 or symbol in self.positions:
                continue
            direction = Direction.LONG if amt > 0 else Direction.SHORT
            entry = float(ep.get("entryPrice", 0))
            qty = abs(amt)
            pos = Position(
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                quantity=qty,
                size_usdt=qty * entry,
                best_price=entry,
                original_risk=0.0,
            )
            self.positions[symbol] = pos
            logger.info(
                f"[LIVE] Recovered position {symbol} "
                f"{direction.value} qty={qty}",
            )

    # -- private: entry -----------------------------------------------------

    async def _place_entry(
        self, signal: Signal, qty: float, price: float,
    ) -> dict[str, Any]:
        side = "BUY" if signal.direction == Direction.LONG else "SELL"
        return await self.executor.place_limit_entry(
            symbol=signal.symbol,
            side=side,
            quantity=qty,
            price=price,
        )

    @staticmethod
    def _create_position(
        signal: Signal, size: float, qty: float,
        resp: dict[str, Any],
        sl_price: float, tp_price: float,
        avg_price: float = 0.0,
    ) -> Position:
        entry = avg_price if avg_price > 0 else signal.entry_price
        return Position(
            signal=signal,
            symbol=signal.symbol,
            direction=signal.direction,
            setup_type=signal.setup_type,
            score=signal.score,
            entry_price=entry,
            sl_price=sl_price,
            tp_price=tp_price,
            size_usdt=size,
            quantity=qty,
            entry_order_id=resp.get("orderId", 0),
            best_price=entry,
            original_risk=abs(entry - sl_price),
        )

    async def _place_protective_orders(self, pos: Position) -> bool:
        close_side = "SELL" if pos.direction == Direction.LONG else "BUY"
        sl_resp = await self.executor.place_stop_loss(
            pos.symbol, close_side, pos.quantity, pos.sl_price,
        )
        if not sl_resp.get("orderId"):
            return False
        pos.sl_order_id = sl_resp["orderId"]
        tp_resp = await self.executor.place_take_profit(
            pos.symbol, close_side, pos.quantity, pos.tp_price,
        )
        if tp_resp.get("orderId"):
            pos.tp_order_id = tp_resp["orderId"]
        return True

    async def _emergency_close(self, pos: Position) -> None:
        """SL placement failed -> immediately market close (rule 9)."""
        side = "SELL" if pos.direction == Direction.LONG else "BUY"
        await self.executor.market_close(pos.symbol, side, pos.quantity)
        logger.error(f"[LIVE] Emergency close {pos.symbol} -- SL failed")

    async def _update_exchange_sl(self, pos: Position) -> None:
        """Cancel old SL/TP and re-place with new SL level."""
        await self.executor.cancel_all(pos.symbol)
        close_side = "SELL" if pos.direction == Direction.LONG else "BUY"
        sl_resp = await self.executor.place_stop_loss(
            pos.symbol, close_side, pos.quantity, pos.sl_price,
        )
        if sl_resp.get("orderId"):
            pos.sl_order_id = sl_resp["orderId"]
        else:
            logger.error(
                f"[LIVE] SL re-place failed for {pos.symbol}, "
                f"emergency close",
            )
            await self._emergency_close(pos)
            self.positions.pop(pos.symbol, None)
            return
        tp_resp = await self.executor.place_take_profit(
            pos.symbol, close_side, pos.quantity, pos.tp_price,
        )
        if tp_resp.get("orderId"):
            pos.tp_order_id = tp_resp["orderId"]

    # -- price tracking & exit logic (mirrors PaperTrader) ------------------

    @staticmethod
    def _update_price_tracking(pos: Position, price: float) -> None:
        if pos.direction == Direction.LONG:
            pos.best_price = max(pos.best_price, price)
        else:
            pos.best_price = (
                min(pos.best_price, price) if pos.best_price else price
            )
        pos.current_pnl = LiveTrader._calc_pnl(pos, price)

    @staticmethod
    def _check_breakeven(
        pos: Position, price: float, ap: AdaptiveParams,
    ) -> None:
        if pos.breakeven_moved:
            return
        atr_val = ap.atr_value
        if atr_val > 0:
            trigger = atr_val * ap.breakeven_trigger_atr
        else:
            risk = pos.original_risk or abs(pos.entry_price - pos.sl_price)
            trigger = risk * BREAKEVEN_TRIGGER_RR
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
    def _check_trailing(
        pos: Position, price: float, ap: AdaptiveParams,
    ) -> bool:
        """Returns True if SL was changed (needs exchange update)."""
        atr_val = ap.atr_value
        if atr_val > 0:
            rr_trigger = atr_val * ap.trail_activation_atr
            trail_distance = max(
                atr_val * ap.trail_distance_atr,
                pos.entry_price * MIN_TRAIL_PCT,
            )
        else:
            risk = pos.original_risk or abs(pos.entry_price - pos.sl_price)
            rr_trigger = risk * TRAILING_ACTIVATION_RR
            trail_distance = max(
                risk * TRAILING_RISK_FACTOR,
                pos.entry_price * MIN_TRAIL_PCT,
            )
        old_sl = pos.sl_price
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
        return pos.sl_price != old_sl

    @staticmethod
    def _check_software_exits(
        pos: Position, snap: MarketSnapshot,
    ) -> str | None:
        """Check exits that the exchange cant handle: CVD divergence, time stop.

        SL/TP are handled by exchange orders -- no need to check here.
        """
        price = snap.price
        elapsed_sec = time.time() - pos.opened_at
        elapsed_min = elapsed_sec / 60
        is_long = pos.direction == Direction.LONG
        in_profit = (
            (price > pos.entry_price) if is_long
            else (price < pos.entry_price)
        )
        # CVD divergence exit -- require significant profit + hold time
        if elapsed_sec >= CVD_EXIT_MIN_HOLD_SEC and in_profit:
            pnl_pct = (
                abs(price - pos.entry_price) / pos.entry_price
                if pos.entry_price else 0
            )
            atr_val = snap.adaptive.atr_value
            atr_profit = abs(price - pos.entry_price)
            pct_ok = pnl_pct >= CVD_EXIT_MIN_PNL_PCT
            atr_ok = (
                atr_val <= 0
                or atr_profit >= atr_val * CVD_EXIT_MIN_ATR_MULT
            )
            if pct_ok and atr_ok:
                if is_long and snap.cvd_delta_1m < 0:
                    return "cvd_divergence"
                if not is_long and snap.cvd_delta_1m > 0:
                    return "cvd_divergence"
        # Time stop -- extend if profitable
        max_hold = MAX_HOLD_IF_PROFIT if in_profit else MAX_HOLD_MINUTES
        if elapsed_min >= max_hold:
            return "time_stop"
        return None

    @staticmethod
    def _calc_pnl(
        pos: Position, price: float, reason: str = "",
    ) -> float:
        if pos.direction == Direction.LONG:
            pnl = (
                (price - pos.entry_price) / pos.entry_price * pos.size_usdt
            )
        else:
            pnl = (
                (pos.entry_price - price) / pos.entry_price * pos.size_usdt
            )
        entry_fee = pos.size_usdt * MAKER_FEE
        if reason == "tp_hit":
            exit_fee = pos.size_usdt * MAKER_FEE
        else:
            exit_fee = pos.size_usdt * TAKER_FEE
        return pnl - entry_fee - exit_fee
