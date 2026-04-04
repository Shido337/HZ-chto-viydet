from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from exchange.binance_client import BinanceClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LEVERAGE = 25
GTX_REJECT_CODE = -5022
MAX_RETRIES = 3
RETRY_DELAY = 0.3


class OrderExecutor:
    """Place / cancel / modify orders with GTX post-only + FOK fallback.

    Caches exchange symbol filters (LOT_SIZE, PRICE_FILTER) so that
    quantity and price are rounded to valid precision before sending.
    """

    def __init__(self, client: BinanceClient) -> None:
        self.client = client
        # symbol → {"tick_size": float, "step_size": float, "min_qty": float, "min_notional": float}
        self._filters: dict[str, dict[str, float]] = {}

    # -- symbol filter loading ----------------------------------------------

    async def load_filters(self) -> None:
        """Fetch exchange info and cache LOT_SIZE / PRICE_FILTER per symbol."""
        try:
            info = await self.client.get_exchange_info()
            for s in info.get("symbols", []):
                sym = s.get("symbol", "")
                tick = 0.01
                step = 0.001
                min_qty = 0.001
                min_notional = 5.0
                for f in s.get("filters", []):
                    ft = f.get("filterType")
                    if ft == "PRICE_FILTER":
                        tick = float(f.get("tickSize", tick))
                    elif ft == "LOT_SIZE":
                        step = float(f.get("stepSize", step))
                        min_qty = float(f.get("minQty", min_qty))
                    elif ft == "MIN_NOTIONAL":
                        min_notional = float(f.get("notional", min_notional))
                self._filters[sym] = {
                    "tick_size": tick,
                    "step_size": step,
                    "min_qty": min_qty,
                    "min_notional": min_notional,
                }
            logger.info(f"Loaded exchange filters for {len(self._filters)} symbols")
        except Exception:
            logger.exception("Failed to load exchange filters")

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to tick_size precision."""
        f = self._filters.get(symbol)
        if not f:
            return price
        tick = f["tick_size"]
        if tick <= 0:
            return price
        precision = max(0, -int(math.floor(math.log10(tick))))
        return round(math.floor(price / tick) * tick, precision)

    def round_quantity(self, symbol: str, qty: float) -> float:
        """Round quantity to step_size precision, respecting min_qty."""
        f = self._filters.get(symbol)
        if not f:
            return qty
        step = f["step_size"]
        min_qty = f["min_qty"]
        if step <= 0:
            return qty
        precision = max(0, -int(math.floor(math.log10(step))))
        rounded = round(math.floor(qty / step) * step, precision)
        if rounded < min_qty:
            return 0.0
        return rounded

    # -- preparation --------------------------------------------------------

    async def prepare_symbol(self, symbol: str) -> None:
        """Set leverage + margin type before first trade on *symbol*."""
        if not self._filters:
            await self.load_filters()
        await self.client.set_leverage(symbol, LEVERAGE)
        try:
            await self.client.set_margin_type(symbol, "ISOLATED")
        except Exception:
            pass  # already ISOLATED

    # -- entry order (GTX → FOK fallback) -----------------------------------

    async def place_limit_entry(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> dict[str, Any]:
        """GTX post-only limit.  Falls back to FOK if GTX rejected."""
        resp = await self.client.place_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTX",
            quantity=quantity,
            price=price,
        )
        code = resp.get("code")
        if code == GTX_REJECT_CODE:
            logger.warning(f"GTX rejected for {symbol}, using FOK fallback")
            resp = await self.client.place_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                timeInForce="FOK",
                quantity=quantity,
                price=price,
            )
        return resp

    # -- protective orders --------------------------------------------------

    async def place_stop_loss(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict[str, Any]:
        return await self._place_protective(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            order_type="STOP_MARKET",
        )

    async def place_take_profit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict[str, Any]:
        return await self._place_protective(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_price=stop_price,
            order_type="TAKE_PROFIT_MARKET",
        )

    async def _place_protective(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        order_type: str,
    ) -> dict[str, Any]:
        """SL/TP with workingType=MARK_PRICE, reduceOnly=true."""
        for attempt in range(1, MAX_RETRIES + 1):
            resp = await self.client.place_order(
                symbol=symbol,
                side=side,
                type=order_type,
                stopPrice=stop_price,
                quantity=quantity,
                workingType="MARK_PRICE",
                reduceOnly="true",
            )
            if resp.get("orderId"):
                return resp
            logger.warning(
                f"Protective {order_type} failed for {symbol}: "
                f"{resp.get('msg')} attempt {attempt}",
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
        return resp

    # -- market close (emergency) -------------------------------------------

    async def market_close(
        self, symbol: str, side: str, quantity: float,
    ) -> dict[str, Any]:
        """Emergency market close — used when SL placement fails."""
        logger.error(f"Emergency market close {symbol} {side} qty={quantity}")
        return await self.client.place_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
            reduceOnly="true",
        )

    # -- cancel helpers -----------------------------------------------------

    async def cancel_order(
        self, symbol: str, order_id: int,
    ) -> dict[str, Any]:
        return await self.client.cancel_order(symbol, order_id)

    async def cancel_all(self, symbol: str) -> dict[str, Any]:
        return await self.client.cancel_all_orders(symbol)
