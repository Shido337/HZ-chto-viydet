from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.signal_generator import Direction, Position, Signal
from data.cache import MarketCache

if TYPE_CHECKING:
    from exchange.binance_client import BinanceClient
    from exchange.order_executor import OrderExecutor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRAILING_ACTIVATION_RR = 1.0
TRAILING_PCT = 0.003
BREAKEVEN_TRIGGER_RR = 0.5
MAX_HOLD_MINUTES = 10
LEVERAGE = 25


class LiveTrader:
    """Real exchange execution with full position lifecycle."""

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

    @property
    def open_count(self) -> int:
        return len(self.positions)

    # -- open position ------------------------------------------------------

    async def open_position(
        self, signal: Signal, size_usdt: float,
    ) -> Position | None:
        await self.executor.prepare_symbol(signal.symbol)
        qty = size_usdt / signal.entry_price if signal.entry_price else 0
        if qty <= 0:
            return None

        entry_resp = await self._place_entry(signal, qty)
        if not entry_resp.get("orderId"):
            return None

        pos = self._create_position(signal, size_usdt, qty, entry_resp)
        ok = await self._place_protective_orders(pos)
        if not ok:
            await self._emergency_close(pos)
            return None

        self.positions[signal.symbol] = pos
        logger.info(
            f"[LIVE] Opened {signal.direction.value} {signal.symbol} "
            f"@ {signal.entry_price:.4f} size=${size_usdt:.2f}",
        )
        return pos

    # -- close position -----------------------------------------------------

    async def close_position(
        self, symbol: str, reason: str,
    ) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        # Cancel SL/TP before closing
        await self.executor.cancel_all(symbol)
        side = "SELL" if pos.direction == Direction.LONG else "BUY"
        await self.executor.market_close(symbol, side, pos.quantity)
        snap = self.cache.get_snapshot(symbol)
        pos.current_pnl = self._calc_pnl(pos, snap.price)
        logger.info(
            f"[LIVE] Closed {symbol} reason={reason} "
            f"pnl={pos.current_pnl:+.4f}",
        )
        return pos

    # -- update loop --------------------------------------------------------

    async def update_positions(self) -> list[tuple[Position, str]]:
        closed: list[tuple[Position, str]] = []
        for symbol in list(self.positions):
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            pos = self.positions[symbol]
            self._update_price_tracking(pos, snap.price)
            self._check_breakeven(pos, snap.price)
            sl_changed = self._check_trailing(pos, snap.price)
            if sl_changed:
                await self._update_exchange_sl(pos)
            reason = self._check_exits(pos, snap)
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
            pos = Position(
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                quantity=abs(amt),
                size_usdt=abs(amt) * entry,
                best_price=entry,
            )
            self.positions[symbol] = pos
            logger.info(f"[LIVE] Recovered position {symbol} {direction.value}")

    # -- private: entry -----------------------------------------------------

    async def _place_entry(
        self, signal: Signal, qty: float,
    ) -> dict[str, Any]:
        side = "BUY" if signal.direction == Direction.LONG else "SELL"
        return await self.executor.place_limit_entry(
            symbol=signal.symbol,
            side=side,
            quantity=qty,
            price=signal.entry_price,
        )

    @staticmethod
    def _create_position(
        signal: Signal, size: float, qty: float, resp: dict[str, Any],
    ) -> Position:
        return Position(
            signal=signal,
            symbol=signal.symbol,
            direction=signal.direction,
            setup_type=signal.setup_type,
            score=signal.score,
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            size_usdt=size,
            quantity=qty,
            entry_order_id=resp.get("orderId", 0),
            best_price=signal.entry_price,
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
        """SL placement failed → immediately market close."""
        side = "SELL" if pos.direction == Direction.LONG else "BUY"
        await self.executor.market_close(pos.symbol, side, pos.quantity)
        logger.error(f"[LIVE] Emergency close {pos.symbol} — SL failed")

    async def _update_exchange_sl(self, pos: Position) -> None:
        """Cancel old SL/TP and re-place with new SL level."""
        await self.executor.cancel_all(pos.symbol)
        close_side = "SELL" if pos.direction == Direction.LONG else "BUY"
        sl_resp = await self.executor.place_stop_loss(
            pos.symbol, close_side, pos.quantity, pos.sl_price,
        )
        if sl_resp.get("orderId"):
            pos.sl_order_id = sl_resp["orderId"]
        tp_resp = await self.executor.place_take_profit(
            pos.symbol, close_side, pos.quantity, pos.tp_price,
        )
        if tp_resp.get("orderId"):
            pos.tp_order_id = tp_resp["orderId"]

    # -- price tracking & exit logic (shared patterns) ----------------------

    @staticmethod
    def _update_price_tracking(pos: Position, price: float) -> None:
        if pos.direction == Direction.LONG:
            pos.best_price = max(pos.best_price, price)
        else:
            pos.best_price = min(pos.best_price, price) if pos.best_price else price
        pos.current_pnl = LiveTrader._calc_pnl(pos, price)

    @staticmethod
    def _check_breakeven(pos: Position, price: float) -> None:
        if pos.breakeven_moved:
            return
        risk = abs(pos.entry_price - pos.sl_price)
        trigger = risk * BREAKEVEN_TRIGGER_RR
        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + trigger:
                pos.sl_price = pos.entry_price
                pos.breakeven_moved = True
        else:
            if price <= pos.entry_price - trigger:
                pos.sl_price = pos.entry_price
                pos.breakeven_moved = True

    @staticmethod
    def _check_trailing(pos: Position, price: float) -> bool:
        """Returns True if SL was changed (needs exchange update)."""
        risk = abs(pos.entry_price - pos.sl_price)
        rr_trigger = risk * TRAILING_ACTIVATION_RR
        old_sl = pos.sl_price

        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price * (1 - TRAILING_PCT)
                if trail_sl > pos.sl_price:
                    pos.sl_price = trail_sl
        else:
            if price <= pos.entry_price - rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price * (1 + TRAILING_PCT)
                if trail_sl < pos.sl_price:
                    pos.sl_price = trail_sl

        return pos.sl_price != old_sl

    @staticmethod
    def _check_exits(pos: Position, snap: Any) -> str | None:
        price = snap.price
        if pos.direction == Direction.LONG and price <= pos.sl_price:
            return "sl_hit"
        if pos.direction == Direction.SHORT and price >= pos.sl_price:
            return "sl_hit"
        if pos.direction == Direction.LONG and price >= pos.tp_price:
            return "tp_hit"
        if pos.direction == Direction.SHORT and price <= pos.tp_price:
            return "tp_hit"
        if pos.direction == Direction.LONG and snap.cvd_delta_1m < 0:
            if price > pos.entry_price:
                return "cvd_divergence"
        if pos.direction == Direction.SHORT and snap.cvd_delta_1m > 0:
            if price < pos.entry_price:
                return "cvd_divergence"
        elapsed = (time.time() - pos.opened_at) / 60
        if elapsed >= MAX_HOLD_MINUTES:
            return "time_stop"
        return None

    @staticmethod
    def _calc_pnl(pos: Position, price: float) -> float:
        if pos.direction == Direction.LONG:
            return (price - pos.entry_price) / pos.entry_price * pos.size_usdt
        return (pos.entry_price - price) / pos.entry_price * pos.size_usdt
