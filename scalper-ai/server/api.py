from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.bot_engine import BotEngine
from core.signal_generator import Position, Signal
from data.database import init_db
from server.ws_manager import WSManager
from utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
setup_logger()
engine = BotEngine()
ws_mgr = WSManager()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    try:
        await init_db()
        engine._on_trade_close = _on_trade_close
        engine._on_signal = _on_signal_new
        engine._on_regime = _on_regime_update
        await engine.start()
        logger.info("SCALPER-AI started successfully")
    except Exception:
        logger.exception("Fatal error during startup")
        raise
    yield
    try:
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


async def _on_regime_update(symbol: str, regime: str) -> None:
    await ws_mgr.broadcast({
        "type": "regime_update",
        "data": {"symbol": symbol, "regime": regime},
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
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


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
    }
