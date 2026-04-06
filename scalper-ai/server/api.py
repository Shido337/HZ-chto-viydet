from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.bot_engine import BotEngine
from core.signal_generator import PendingOrder, Position, Signal
from data.cache import MarketSnapshot
from data.database import init_db
from server.ws_manager import WSManager
from utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
setup_logger()
engine = BotEngine()
ws_mgr = WSManager()

BROADCAST_INTERVAL = 2.0  # seconds between periodic broadcasts
_broadcast_task: asyncio.Task[None] | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    global _broadcast_task
    try:
        await init_db()
        engine._on_trade_close = _on_trade_close
        engine._on_signal = _on_signal_new
        engine._on_signal_expired = _on_signal_expired
        engine._on_regime = _on_regime_update
        engine._on_position_opened = _on_position_opened
        engine._on_kline_update = _on_kline_update
        engine._on_pending_placed = _on_pending_placed
        engine._on_pending_cancelled = _on_pending_cancelled
        await engine.start()
        _broadcast_task = asyncio.create_task(_broadcast_loop())
        logger.info("SCALPER-AI started successfully")
    except Exception:
        logger.exception("Fatal error during startup")
        raise
    yield
    try:
        if _broadcast_task and not _broadcast_task.done():
            _broadcast_task.cancel()
        await engine.stop()
        logger.info("SCALPER-AI stopped")
    except Exception:
        logger.exception("Error during shutdown")


app = FastAPI(title="SCALPER-AI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Trade close callback
# ---------------------------------------------------------------------------
async def _on_trade_close(pos: Position, reason: str) -> None:
    await ws_mgr.broadcast({
        "type": "trade_closed",
        "data": {
            "symbol": pos.symbol,
            "direction": pos.direction.value,
            "pnl": pos.current_pnl,
            "reason": reason,
        },
    })
    # Broadcast updated balance after trade
    bal = engine.risk.session_start_balance + engine.risk.daily_pnl
    await ws_mgr.broadcast({
        "type": "balance_update",
        "data": {"balance": round(bal, 2), "daily_pnl": round(engine.risk.daily_pnl, 4)},
    })


async def _on_signal_new(signal: Signal) -> None:
    await ws_mgr.broadcast({
        "type": "signal_new",
        "data": {
            "id": signal.id,
            "symbol": signal.symbol,
            "direction": signal.direction.value,
            "setup_type": signal.setup_type.value,
            "score": signal.score,
            "entry_price": signal.entry_price,
            "sl_price": signal.sl_price,
            "tp_price": signal.tp_price,
            "created_at": signal.created_at,
        },
    })


async def _on_signal_expired(signal: Signal) -> None:
    await ws_mgr.broadcast({
        "type": "signal_expired",
        "data": {"id": signal.id},
    })


async def _on_regime_update(symbol: str, regime: str) -> None:
    await ws_mgr.broadcast({
        "type": "regime_update",
        "data": {"symbol": symbol, "regime": regime},
    })


async def _on_position_opened(pos: Position) -> None:
    await ws_mgr.broadcast({
        "type": "position_opened",
        "data": _serialize_position(pos),
    })


# Throttle kline broadcasts: max once per second per symbol+tf
_kline_last_sent: dict[str, float] = {}
_KLINE_THROTTLE = 1.0  # seconds


async def _on_kline_update(symbol: str, tf: str, candle: dict[str, Any]) -> None:
    import time as _time
    # Always send closed candles immediately
    if not candle.get("closed", False):
        key = f"{symbol}:{tf}"
        now = _time.monotonic()
        last = _kline_last_sent.get(key, 0.0)
        if now - last < _KLINE_THROTTLE:
            return
        _kline_last_sent[key] = now
    await ws_mgr.broadcast({
        "type": "kline_update",
        "data": {"symbol": symbol, "tf": tf, "candle": candle},
    })


async def _on_pending_placed(order: PendingOrder) -> None:
    await ws_mgr.broadcast({
        "type": "pending_order_placed",
        "data": {
            "symbol": order.symbol,
            "direction": order.direction.value,
            "setup_type": order.setup_type.value,
            "price": order.entry_price,
            "size_usdt": order.size_usdt,
            "notional": order.size_usdt,
            "expiry": order.expiry * 1000,  # JS timestamp (ms)
        },
    })


async def _on_pending_cancelled(order: PendingOrder) -> None:
    await ws_mgr.broadcast({
        "type": "pending_order_cancelled",
        "data": {"symbol": order.symbol},
    })


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return {
        "mode": engine.mode,
        "symbols": engine.symbols,
        "strategies": engine.strategy_enabled,
        "positions": len(engine.trader.positions),
    }


@app.get("/api/positions")
async def get_positions() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for pos in engine.trader.positions.values():
        result.append(_serialize_position(pos))
    return result


@app.get("/api/balance")
async def get_balance() -> dict[str, Any]:
    bal = engine.risk.session_start_balance + engine.risk.daily_pnl
    return {
        "balance": bal,
        "daily_pnl": engine.risk.daily_pnl,
        "session_start": engine.risk.session_start_balance,
    }


@app.get("/api/ml/stats")
async def get_ml_stats() -> dict[str, Any]:
    return engine.learner.get_stats()


@app.get("/api/klines/{symbol}")
async def get_klines(symbol: str) -> dict[str, Any]:
    """Return cached klines for a symbol (all timeframes)."""
    snap = engine.cache.get_snapshot(symbol)
    return _serialize_snapshot(snap, include_klines=True)


@app.get("/api/signals")
async def get_signals() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for sig in engine.signals:
        result.append({
            "id": sig.id,
            "symbol": sig.symbol,
            "direction": sig.direction.value,
            "setup_type": sig.setup_type.value,
            "score": sig.score,
            "entry_price": sig.entry_price,
            "sl_price": sig.sl_price,
            "tp_price": sig.tp_price,
            "created_at": sig.created_at,
        })
    return result


@app.post("/api/mode/{mode}")
async def set_mode(mode: str) -> dict[str, str]:
    if mode not in ("paper", "live"):
        return {"error": "Invalid mode"}
    if engine.trader.open_count > 0:
        return {"error": "Close all positions before switching mode"}
    engine.switch_mode(mode)
    if mode == "live":
        await engine.recover_live_positions()
    logger.info(f"Mode switched to {mode}")
    return {"mode": mode}


@app.post("/api/stop")
async def emergency_stop() -> dict[str, str]:
    for symbol in list(engine.trader.positions):
        if hasattr(engine.trader, "close_position"):
            if asyncio.iscoroutinefunction(engine.trader.close_position):
                await engine.trader.close_position(symbol, "emergency_stop")
            else:
                engine.trader.close_position(symbol, engine.cache.get_snapshot(symbol).price, "emergency_stop")
    return {"status": "stopped"}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return {
        "mode": engine.mode,
        "size_mode": engine.risk.mode.value,
        "fixed_amount": engine.risk.fixed_amount,
        "adaptive_base": engine.risk.adaptive_base,
        "percent_value": engine.risk.percent_value,
        "symbols": engine.symbols,
        "strategies": engine.strategy_enabled,
        "leverage": 25,
        "max_positions": 5,
        "daily_loss_limit": 15,
    }


@app.post("/api/settings")
async def update_settings(body: dict[str, Any]) -> dict[str, str]:
    if "size_mode" in body:
        engine.risk.mode = body["size_mode"]
    if "fixed_amount" in body:
        engine.risk.fixed_amount = float(body["fixed_amount"])
    if "adaptive_base" in body:
        engine.risk.adaptive_base = float(body["adaptive_base"])
    if "percent_value" in body:
        engine.risk.percent_value = float(body["percent_value"])
    if "strategies" in body:
        engine.strategy_enabled.update(body["strategies"])
    return {"status": "ok"}


@app.get("/api/trades")
async def get_trades(limit: int = 200) -> list[dict[str, Any]]:
    """Return last N trades from DB for monitoring."""
    from data.database import async_session_factory
    from data.models import Trade
    from sqlalchemy import select

    async with async_session_factory() as session:
        stmt = select(Trade).order_by(Trade.id.desc()).limit(min(limit, 1000))
        result = await session.execute(stmt)
        trades = result.scalars().all()
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction.value if t.direction else "",
            "setup_type": t.setup_type.value if t.setup_type else "",
            "score": t.score,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "sl_price": t.sl_price,
            "tp_price": t.tp_price,
            "size_usdt": t.size_usdt,
            "pnl": t.pnl,
            "result": t.result.value if t.result else "",
            "exit_reason": t.exit_reason,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }
        for t in trades
    ]


@app.get("/api/trades/summary")
async def get_trades_summary() -> dict[str, Any]:
    """Aggregate trade stats for monitoring."""
    from data.database import async_session_factory
    from data.models import Trade
    from sqlalchemy import func, select

    async with async_session_factory() as session:
        total = await session.scalar(select(func.count(Trade.id))) or 0
        total_pnl = await session.scalar(select(func.sum(Trade.pnl))) or 0.0
        wins = await session.scalar(
            select(func.count(Trade.id)).where(Trade.pnl > 0),
        ) or 0
        losses = await session.scalar(
            select(func.count(Trade.id)).where(Trade.pnl < 0),
        ) or 0
    win_rate = (wins / total * 100) if total > 0 else 0.0
    return {
        "total_trades": total,
        "total_pnl": round(total_pnl, 4),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "balance": round(
            engine.risk.session_start_balance + engine.risk.daily_pnl, 2,
        ),
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_mgr.connect(ws)
    try:
        await _send_init_state(ws)
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


# ---------------------------------------------------------------------------
# Periodic broadcast loop
# ---------------------------------------------------------------------------
async def _broadcast_loop() -> None:
    """Broadcast lightweight market data + positions + balance every 2s."""
    while True:
        try:
            await asyncio.sleep(BROADCAST_INTERVAL)
            if not ws_mgr._connections:
                continue
            # Lightweight market snapshots (no klines)
            for symbol in engine.symbols:
                snap = engine.cache.get_snapshot(symbol)
                await ws_mgr.broadcast({
                    "type": "market_snapshot",
                    "data": _serialize_snapshot(snap, include_klines=False),
                })
            # Position updates
            for pos in engine.trader.positions.values():
                await ws_mgr.broadcast({
                    "type": "position_updated",
                    "data": _serialize_position(pos),
                })
            # Pending limit orders
            if hasattr(engine.trader, "pending"):
                for order in engine.trader.pending.values():
                    await ws_mgr.broadcast({
                        "type": "pending_order_placed",
                        "data": {
                            "symbol": order.symbol,
                            "direction": order.direction.value,
                            "setup_type": order.setup_type.value,
                            "price": order.entry_price,
                            "size_usdt": order.size_usdt,
                            "notional": order.size_usdt,
                            "expiry": order.expiry * 1000,
                        },
                    })
            # Balance
            bal = engine.risk.session_start_balance + engine.risk.daily_pnl
            await ws_mgr.broadcast({
                "type": "balance_update",
                "data": {
                    "balance": round(bal, 2),
                    "daily_pnl": round(engine.risk.daily_pnl, 4),
                },
            })
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Broadcast loop error")


# ---------------------------------------------------------------------------
# Initial state on WS connect
# ---------------------------------------------------------------------------
async def _send_init_state(ws: WebSocket) -> None:
    """Push full state to a newly-connected dashboard client."""
    try:
        regimes: dict[str, str] = {}
        for s in engine.symbols:
            r = engine.cache.regime.get(s)
            if r is not None and hasattr(r, "value"):
                regimes[s] = r.value
            else:
                regimes[s] = str(r) if r else "RANGING"

        bal = engine.risk.session_start_balance + engine.risk.daily_pnl

        await ws.send_json({
            "type": "init_state",
            "data": {
                "symbols": engine.symbols,
                "balance": round(bal, 2),
                "daily_pnl": round(engine.risk.daily_pnl, 4),
                "mode": engine.mode,
                "regimes": regimes,
                "started_at": engine.started_at,
            },
        })

        # Full snapshots with klines
        for symbol in engine.symbols:
            snap = engine.cache.get_snapshot(symbol)
            await ws.send_json({
                "type": "market_snapshot",
                "data": _serialize_snapshot(snap, include_klines=True),
            })

        # Active positions
        for pos in engine.trader.positions.values():
            await ws.send_json({
                "type": "position_opened",
                "data": _serialize_position(pos),
            })

        # Pending limit orders
        if hasattr(engine.trader, "pending"):
            for order in engine.trader.pending.values():
                await ws.send_json({
                    "type": "pending_order_placed",
                    "data": {
                        "symbol": order.symbol,
                        "direction": order.direction.value,
                        "setup_type": order.setup_type.value,
                        "price": order.entry_price,
                        "size_usdt": order.size_usdt,
                        "notional": order.size_usdt,
                        "expiry": order.expiry * 1000,
                    },
                })

        # Recent signals
        for sig in engine.signals[-50:]:
            await ws.send_json({
                "type": "signal_new",
                "data": {
                    "id": sig.id,
                    "symbol": sig.symbol,
                    "direction": sig.direction.value,
                    "setup_type": sig.setup_type.value,
                    "score": sig.score,
                    "entry_price": sig.entry_price,
                    "sl_price": sig.sl_price,
                    "tp_price": sig.tp_price,
                    "created_at": sig.created_at,
                },
            })
        logger.info("Init state sent to WS client")
    except WebSocketDisconnect:
        raise
    except Exception:
        logger.exception("Failed to send init state")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _serialize_position(pos: Position) -> dict[str, Any]:
    return {
        "id": pos.id,
        "symbol": pos.symbol,
        "direction": pos.direction.value,
        "setup_type": pos.setup_type.value,
        "score": pos.score,
        "entry_price": pos.entry_price,
        "sl_price": pos.sl_price,
        "tp_price": pos.tp_price,
        "size_usdt": pos.size_usdt,
        "current_pnl": pos.current_pnl,
        "liquidation_price": pos.liquidation_price,
        "trailing_activated": pos.trailing_activated,
        "breakeven_moved": pos.breakeven_moved,
        "best_price": pos.best_price,
    }


def _serialize_snapshot(
    snap: MarketSnapshot, *, include_klines: bool = False,
) -> dict[str, Any]:
    ind = snap.indicators
    data: dict[str, Any] = {
        "symbol": snap.symbol,
        "price": snap.price,
        "bid": snap.bid,
        "ask": snap.ask,
        "bid_qty": snap.bid_qty,
        "ask_qty": snap.ask_qty,
        "cvd": snap.cvd,
        "cvd_delta_1m": snap.cvd_delta_1m,
        "volume_1m": snap.volume_1m,
        "regime": snap.regime.value if hasattr(snap.regime, "value") else str(snap.regime),
        "indicators": {
            "adx": ind.adx,
            "atr": ind.atr,
            "ema9": ind.ema9,
            "ema21": ind.ema21,
            "vwap": ind.vwap,
            "rsi": ind.rsi,
            "atr_percentile": ind.atr_percentile,
        },
        "klines_1m": list(snap.klines_1m) if include_klines else [],
        "klines_3m": list(snap.klines_3m) if include_klines else [],
        "klines_5m": list(snap.klines_5m) if include_klines else [],
    }
    return data
