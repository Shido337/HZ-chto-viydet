from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.signal_generator import Direction, Position, Signal
from data.cache import MarketCache

if TYPE_CHECKING:
    from data.cache import AdaptiveParams, MarketSnapshot
    from exchange.binance_client import BinanceClient
    from exchange.order_executor import OrderExecutor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BREAKEVEN_TRIGGER_RR = 0.6    # fallback BE trigger if no ATR
TRAILING_ACTIVATION_RR = 0.5  # fallback real trail activation
TRAILING_RISK_FACTOR = 0.4    # fallback trail distance
MIN_TRAIL_PCT = 0.0003        # 0.03% absolute minimum trail
MAX_HOLD_MINUTES = 8
MAX_HOLD_IF_PROFIT = 12
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.003
CVD_EXIT_MIN_ATR_MULT = 0.5
CVD_EXIT_MIN_HOLD_SEC = 120
MAKER_FEE = 0.0002
TAKER_FEE = 0.0004
# Binance callbackRate limits
MIN_CALLBACK_RATE = 0.1  # 0.1%
MAX_CALLBACK_RATE = 5.0  # 5.0%


class LiveTrader:
    """Real exchange execution with 2-stage trailing lifecycle.

    Stage 1 (at entry): SL + TP + BE-trailing (TRAILING_STOP_MARKET
        with small callbackRate — activates at BE trigger and locks
        in breakeven profit when it fires).
    Stage 2 (price hits real trail level — one-time upgrade):
        Cancel BE-trailing → place real TRAILING_STOP_MARKET with
        proper callbackRate from ATR (activates immediately since
        price already past activation).
    All 3 protective orders live on Binance — software only does
    CVD divergence exit, time stop, and the one-time trail upgrade.
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
        # Positions closed by exchange (SL/TP/trailing hit on Binance side)
        self._exchange_closed: dict[str, str] = {}  # symbol -> reason
        # Track which positions have been upgraded to real trailing
        self._trail_upgraded: set[str] = set()

    @property
    def open_count(self) -> int:
        return len(self.positions)

    # -- exchange event handler (called from user data stream) --------------

    async def on_order_update(self, data: dict[str, Any]) -> None:
        """Handle ORDER_TRADE_UPDATE from Binance user data stream.

        Detects when exchange-side SL, TP, or trailing fires so we
        dont try to close the position again ourselves.
        """
        order = data.get("o", {})
        symbol = order.get("s", "")
        status = order.get("X", "")  # FILLED, PARTIALLY_FILLED, etc.
        order_type = order.get("ot", "")  # STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET
        reduce_only = order.get("R", False)  # reduceOnly flag

        if symbol not in self.positions:
            return

        if status != "FILLED":
            return

        realized_pnl = float(order.get("rp", 0))

        # Exchange SL fired
        if order_type == "STOP_MARKET" and reduce_only:
            logger.info(
                f"[LIVE] Exchange SL FILLED {symbol} "
                f"realized_pnl={realized_pnl:+.4f}",
            )
            self._exchange_closed[symbol] = "sl_hit"

        # Exchange TP fired
        elif order_type == "TAKE_PROFIT_MARKET" and reduce_only:
            logger.info(
                f"[LIVE] Exchange TP FILLED {symbol} "
                f"realized_pnl={realized_pnl:+.4f}",
            )
            self._exchange_closed[symbol] = "tp_hit"

        # Exchange trailing stop fired
        elif order_type == "TRAILING_STOP_MARKET" and reduce_only:
            logger.info(
                f"[LIVE] Exchange TRAILING FILLED {symbol} "
                f"realized_pnl={realized_pnl:+.4f}",
            )
            self._exchange_closed[symbol] = "trailing_stop"

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

        # Stage 1: SL + TP + BE-trailing (all on Binance)
        snap = self.cache.get_snapshot(signal.symbol)
        ok = await self._place_stage1_orders(pos, snap.adaptive)
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
        self._trail_upgraded.discard(symbol)
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
                reason = self._exchange_closed.get(symbol, "exchange_event")
                p = await self.close_position(symbol, reason)
                if p:
                    closed.append((p, reason))

        for symbol in list(self.positions):
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            pos = self.positions[symbol]
            self._update_price_tracking(pos, snap.price)

            # Stage 2: upgrade BE-trailing → real trailing (one-time)
            if symbol not in self._trail_upgraded:
                if self._should_upgrade_trail(pos, snap.price, snap.adaptive):
                    await self._upgrade_to_real_trail(pos, snap.adaptive)

            # Software exits (CVD divergence, time stop)
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

    async def _place_stage1_orders(
        self, pos: Position, ap: AdaptiveParams,
    ) -> bool:
        """Stage 1: SL (original risk) + TP + BE-trailing on Binance."""
        close_side = "SELL" if pos.direction == Direction.LONG else "BUY"

        # 1. Hard SL (STOP_MARKET — original risk level)
        sl_resp = await self.executor.place_stop_loss(
            pos.symbol, close_side, pos.quantity, pos.sl_price,
        )
        if not sl_resp.get("orderId"):
            return False
        pos.sl_order_id = sl_resp["orderId"]

        # 2. TP (TAKE_PROFIT_MARKET)
        tp_resp = await self.executor.place_take_profit(
            pos.symbol, close_side, pos.quantity, pos.tp_price,
        )
        if tp_resp.get("orderId"):
            pos.tp_order_id = tp_resp["orderId"]

        # 3. BE-trailing (TRAILING_STOP_MARKET — small callbackRate)
        #    Activates at BE trigger; when it fires, stop ≈ entry+fees
        be_activation, be_callback = self._calc_be_trailing_params(pos, ap)
        if be_callback > 0:
            trail_resp = await self.executor.place_trailing_stop(
                symbol=pos.symbol,
                side=close_side,
                quantity=pos.quantity,
                callback_rate=be_callback,
                activation_price=be_activation,
            )
            if trail_resp.get("orderId"):
                pos.trail_order_id = trail_resp["orderId"]
                logger.info(
                    f"[LIVE] BE-trail set {pos.symbol} "
                    f"activation={be_activation:.6f} "
                    f"callback={be_callback}%",
                )
            else:
                logger.warning(
                    f"[LIVE] BE-trail placement failed {pos.symbol}, "
                    f"continuing with SL+TP only",
                )
        return True

    @staticmethod
    def _should_upgrade_trail(
        pos: Position, price: float, ap: AdaptiveParams,
    ) -> bool:
        """Check if price reached real trailing activation level."""
        entry = pos.entry_price
        atr_val = ap.atr_value
        if atr_val > 0:
            activation_dist = atr_val * ap.trail_activation_atr
        else:
            risk = pos.original_risk or abs(entry - pos.sl_price)
            activation_dist = risk * TRAILING_ACTIVATION_RR

        if pos.direction == Direction.LONG:
            return price >= entry + activation_dist
        return price <= entry - activation_dist

    async def _upgrade_to_real_trail(
        self, pos: Position, ap: AdaptiveParams,
    ) -> None:
        """Stage 2: Cancel BE-trailing → place real trailing.

        Only the trailing order is replaced. SL and TP stay untouched.
        """
        close_side = "SELL" if pos.direction == Direction.LONG else "BUY"

        # Cancel just the BE-trailing order
        if pos.trail_order_id:
            await self.executor.cancel_order(pos.symbol, pos.trail_order_id)
            pos.trail_order_id = 0

        # Place real trailing (activates immediately — price already past)
        activation, callback = self._calc_real_trailing_params(pos, ap)
        if callback <= 0:
            self._trail_upgraded.add(pos.symbol)
            return

        trail_resp = await self.executor.place_trailing_stop(
            symbol=pos.symbol,
            side=close_side,
            quantity=pos.quantity,
            callback_rate=callback,
            activation_price=activation,
        )
        if trail_resp.get("orderId"):
            pos.trail_order_id = trail_resp["orderId"]
            logger.info(
                f"[LIVE] Trail upgraded {pos.symbol} "
                f"activation={activation:.6f} callback={callback}%",
            )
        else:
            logger.warning(
                f"[LIVE] Real trail placement failed {pos.symbol}",
            )
        self._trail_upgraded.add(pos.symbol)

    async def _emergency_close(self, pos: Position) -> None:
        """SL placement failed -> immediately market close (rule 9)."""
        side = "SELL" if pos.direction == Direction.LONG else "BUY"
        await self.executor.market_close(pos.symbol, side, pos.quantity)
        logger.error(f"[LIVE] Emergency close {pos.symbol} -- SL failed")

    # -- trailing params calculation ----------------------------------------

    @staticmethod
    def _calc_be_trailing_params(
        pos: Position, ap: AdaptiveParams,
    ) -> tuple[float, float]:
        """Calculate BE-trailing (activation_price, callback_rate).

        The BE-trailing activates when price reaches breakeven trigger.
        Its callbackRate is small so that when it fires, the stop
        lands near entry + fees (breakeven).

        For LONG: activation = entry + be_trigger
                  callback = (activation - be_stop) / activation * 100
                  where be_stop = entry + fee_buffer
        """
        entry = pos.entry_price
        if entry <= 0:
            return 0.0, 0.0

        atr_val = ap.atr_value
        if atr_val > 0:
            be_trigger = atr_val * ap.breakeven_trigger_atr
        else:
            risk = pos.original_risk or abs(entry - pos.sl_price)
            be_trigger = risk * BREAKEVEN_TRIGGER_RR

        if be_trigger <= 0:
            return 0.0, 0.0

        fee_buffer = entry * (MAKER_FEE + TAKER_FEE)

        if pos.direction == Direction.LONG:
            activation = entry + be_trigger
            be_stop = entry + fee_buffer
            # callback% = (activation - be_stop) / activation * 100
            callback = (activation - be_stop) / activation * 100
        else:
            activation = entry - be_trigger
            be_stop = entry - fee_buffer
            # callback% = (be_stop - activation) / activation * 100
            callback = (be_stop - activation) / activation * 100

        callback = round(callback, 1)
        callback = max(MIN_CALLBACK_RATE, min(MAX_CALLBACK_RATE, callback))
        return activation, callback

    @staticmethod
    def _calc_real_trailing_params(
        pos: Position, ap: AdaptiveParams,
    ) -> tuple[float, float]:
        """Calculate real trailing (activation_price, callback_rate).

        Activation is set at entry so trailing activates immediately
        (price is already past real trail activation at this point).
        callbackRate is the proper ATR-based trail distance.
        """
        entry = pos.entry_price
        if entry <= 0:
            return 0.0, 0.0

        atr_val = ap.atr_value
        if atr_val > 0:
            trail_dist = max(
                atr_val * ap.trail_distance_atr,
                entry * MIN_TRAIL_PCT,
            )
        else:
            risk = pos.original_risk or abs(entry - pos.sl_price)
            trail_dist = max(
                risk * TRAILING_RISK_FACTOR,
                entry * MIN_TRAIL_PCT,
            )

        # callbackRate = trail distance as percentage of price
        callback = round((trail_dist / entry) * 100, 1)
        callback = max(MIN_CALLBACK_RATE, min(MAX_CALLBACK_RATE, callback))

        # Activate at entry — will trigger immediately since price > entry
        return entry, callback

    # -- price tracking & exit logic ----------------------------------------

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
