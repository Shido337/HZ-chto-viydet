---
description: "Debug trading bot issues: signal not firing, wrong regime, position not opening, WebSocket disconnects, exchange errors, or dashboard not updating."
---

# Debug SCALPER-AI Issue

## Inputs
- **Symptom**: what's happening (or not happening)
- **Module**: which part (strategy, cache, engine, exchange, dashboard)

## Diagnostic Steps

### Signal not firing
1. Check regime: `core/regime_classifier.py` — is ADX in correct range?
2. Check snapshot data: is `klines_1m`/`klines_3m`/`klines_5m` populated?
3. Check each condition in strategy — which one fails?
4. Check `MIN_SIGNAL_SCORE` in `bot_engine.py` (default 0.65)
5. Check `risk_manager.can_open_position()` — daily limit? max positions?

### Position not opening
1. Check `risk_manager.can_open_position()` — are limits hit?
2. Check if symbol already in `trader.positions`
3. Check balance > 0 and position size > $1
4. Check exchange API response for errors

### WebSocket disconnect
1. Check `binance_ws.py` — reconnect loop running?
2. Check cache `_stale` flag — is data marked stale?
3. Check if combined stream URL exceeds 200 streams

### Dashboard not updating
1. Check WS connection: `wsConnected` in store
2. Check `useWebSocket.ts` event handler covers the event type
3. Check `tradingStore.ts` action updates the correct state slice
4. Check component reads from correct store selector

### Exchange order rejected
1. Check error code in logs
2. Common: insufficient margin, invalid quantity precision, leverage not set
3. Check `order_executor.py` retry logic — all 3 attempts failed?
