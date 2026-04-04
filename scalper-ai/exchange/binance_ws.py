from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

import aiohttp
from loguru import logger

WS_BASE = "wss://fstream.binance.com/stream?streams="
TESTNET_WS_BASE = "wss://stream.binancefuture.com/stream?streams="
RECONNECT_DELAY = 3.0
MAX_STREAMS_PER_CONN = 200


class BinanceWS:
    """Combined-stream WebSocket manager with auto-reconnect."""

    def __init__(self, testnet: bool = False) -> None:
        self._base = TESTNET_WS_BASE if testnet else WS_BASE
        self._handlers: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # -- public API ---------------------------------------------------------

    def subscribe(
        self,
        stream: str,
        handler: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Register *stream* → *handler* mapping before calling run()."""
        self._handlers[stream] = handler

    async def start(self) -> None:
        from aiohttp.resolver import ThreadedResolver

        resolver = ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        self._session = aiohttp.ClientSession(connector=connector)
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
        if self._task:
            self._task.cancel()

    # -- internal -----------------------------------------------------------

    def _build_url(self) -> str:
        streams = "/".join(self._handlers.keys())
        return f"{self._base}{streams}"

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._connect_and_listen()
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ConnectionError,
            ) as exc:
                logger.warning(f"WS error: {exc}, reconnecting…")
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Unexpected WS loop error")
            if self._running:
                await asyncio.sleep(RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        assert self._session is not None
        url = self._build_url()
        logger.info(f"WS connecting: {len(self._handlers)} streams")
        async with self._session.ws_connect(url) as ws:
            self._ws = ws
            logger.info("WS connected")
            msg_count = 0
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    msg_count += 1
                    if msg_count == 1:
                        logger.info(f"WS first message received")
                    if msg_count % 10000 == 0:
                        logger.info(f"WS messages processed: {msg_count}")
                    await self._dispatch(msg.json())
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        stream = payload.get("stream", "")
        data = payload.get("data", {})
        handler = self._handlers.get(stream)
        if handler:
            try:
                await handler(data)
            except Exception:
                logger.exception(f"Handler error for {stream}")
        else:
            if not hasattr(self, "_unknown_warned"):
                self._unknown_warned: set[str] = set()
            if stream not in self._unknown_warned:
                self._unknown_warned.add(stream)
                logger.warning(f"No handler for stream: {stream}")
