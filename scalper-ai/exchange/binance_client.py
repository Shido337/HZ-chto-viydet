from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://fapi.binance.com"
TESTNET_URL = "https://testnet.binancefuture.com"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds


class BinanceClient:
    """Async Binance Futures REST client with HMAC signing & retry."""

    def __init__(self) -> None:
        self.api_key = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        self.base = TESTNET_URL if testnet else BASE_URL
        self._session: aiohttp.ClientSession | None = None

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        from aiohttp.resolver import ThreadedResolver

        resolver = ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        self._session = aiohttp.ClientSession(
            headers={"X-MBX-APIKEY": self.api_key},
            connector=connector,
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # -- signing ------------------------------------------------------------

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        qs = urlencode(params)
        sig = hmac.new(
            self.api_secret.encode(), qs.encode(), hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    # -- generic request with retry -----------------------------------------

    async def _request(
        self, method: str, path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        assert self._session is not None, "Call start() first"
        params = dict(params) if params else {}
        if signed:
            params = self._sign(params)

        url = f"{self.base}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._session.request(
                    method, url, params=params,
                )
                data = await resp.json()
                if resp.status >= 400:
                    code = data.get("code", resp.status)
                    msg = data.get("msg", "unknown")
                    logger.warning(
                        f"Binance {method} {path} err {code}: {msg} "
                        f"(attempt {attempt})",
                    )
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(
                            RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                        )
                        continue
                    return data
                return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning(
                    f"Binance {method} {path} net error: {exc} "
                    f"(attempt {attempt})",
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(
                        RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                    )
        return {}

    # -- public endpoints ---------------------------------------------------

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 500,
    ) -> list[dict[str, Any]]:
        raw = await self._request(
            "GET", "/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        if not isinstance(raw, list):
            return []
        return [_parse_kline(k) for k in raw]

    async def get_ticker_price(self, symbol: str) -> float:
        data = await self._request(
            "GET", "/fapi/v1/ticker/price", params={"symbol": symbol},
        )
        return float(data.get("price", 0))

    async def get_exchange_info(self) -> dict[str, Any]:
        data = await self._request("GET", "/fapi/v1/exchangeInfo")
        return data if isinstance(data, dict) else {}

    # -- private (signed) endpoints -----------------------------------------

    async def get_balance(self) -> float:
        data = await self._request(
            "GET", "/fapi/v2/balance", signed=True,
        )
        if not isinstance(data, list):
            return 0.0
        for asset in data:
            if asset.get("asset") == "USDT":
                return float(asset.get("balance", 0))
        return 0.0

    async def get_positions(self) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "/fapi/v2/positionRisk", signed=True,
        )
        if not isinstance(data, list):
            return []
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    async def get_open_orders(
        self, symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request(
            "GET", "/fapi/v1/openOrders", params=params, signed=True,
        )
        return data if isinstance(data, list) else []

    async def set_leverage(self, symbol: str, leverage: int = 25) -> None:
        await self._request(
            "POST", "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
            signed=True,
        )

    async def set_margin_type(self, symbol: str, margin: str = "ISOLATED") -> None:
        await self._request(
            "POST", "/fapi/v1/marginType",
            params={"symbol": symbol, "marginType": margin},
            signed=True,
        )

    async def place_order(self, **params: Any) -> dict[str, Any]:
        data = await self._request(
            "POST", "/fapi/v1/order", params=params, signed=True,
        )
        return data if isinstance(data, dict) else {}

    async def cancel_order(
        self, symbol: str, order_id: int,
    ) -> dict[str, Any]:
        data = await self._request(
            "DELETE", "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        data = await self._request(
            "DELETE", "/fapi/v1/allOpenOrders",
            params={"symbol": symbol},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    async def get_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        data = await self._request(
            "GET", "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    # -- user data stream (listenKey) ---------------------------------------

    async def create_listen_key(self) -> str:
        data = await self._request(
            "POST", "/fapi/v1/listenKey", signed=False,
        )
        return data.get("listenKey", "") if isinstance(data, dict) else ""

    async def keepalive_listen_key(self) -> None:
        await self._request("PUT", "/fapi/v1/listenKey", signed=False)

    # -- screening endpoints (public, unsigned) -----------------------------

    async def get_all_tickers_24hr(self) -> list[dict[str, Any]]:
        """GET /fapi/v1/ticker/24hr — weight 40 (no symbol)."""
        data = await self._request("GET", "/fapi/v1/ticker/24hr")
        return data if isinstance(data, list) else []

    async def get_all_book_tickers(self) -> list[dict[str, Any]]:
        """GET /fapi/v1/ticker/bookTicker — weight 5 (no symbol)."""
        data = await self._request("GET", "/fapi/v1/ticker/bookTicker")
        return data if isinstance(data, list) else []

    async def get_exchange_info_symbols(self) -> list[dict[str, Any]]:
        """Extract symbol list from exchangeInfo (perpetual USDT-M only)."""
        info = await self.get_exchange_info()
        symbols = info.get("symbols", [])
        return [
            s for s in symbols
            if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        ]

    async def get_depth(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        """GET /fapi/v1/depth — weight 5 (limit≤50)."""
        data = await self._request(
            "GET", "/fapi/v1/depth",
            params={"symbol": symbol, "limit": limit},
        )
        return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_kline(k: list[Any]) -> dict[str, Any]:
    return {
        "t": int(k[0]),
        "o": float(k[1]),
        "h": float(k[2]),
        "l": float(k[3]),
        "c": float(k[4]),
        "v": float(k[5]),
        "T": int(k[6]),
        "closed": True,
    }
