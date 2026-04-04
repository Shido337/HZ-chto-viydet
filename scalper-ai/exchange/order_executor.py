from __future__ import annotations

import asyncio
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
    """Place / cancel / modify orders with GTX post-only + FOK fallback."""

    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    # -- preparation --------------------------------------------------------

    async def prepare_symbol(self, symbol: str) -> None:
        """Set leverage + margin type before first trade on *symbol*."""
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
