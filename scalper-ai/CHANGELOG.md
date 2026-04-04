# SCALPER-AI CHANGELOG

## [2026-04-04 01:00 UTC]
Tighten EarlyMomentum: CVD bars 1->3, OB 52->58%, trend EMA filter, proximity 1.5->1.0%
Files: strategies/early_momentum.py

## [2026-04-04 07:11 UTC]
Scalp reality fix: TP 1.5/1.2/1.618 (was 3/2/2.618), trail 0.3RR/0.15%, BE 0.2RR, 5min hold, CVD exit 0.1%
Files: strategies/continuation_break.py, strategies/mean_reversion.py, strategies/early_momentum.py, core/paper_trader.py

## [2026-04-04 07:29 UTC]
Dynamic CoinScreener: auto-select top coins by volume/spread/volatility every 5min
Files: core/coin_screener.py, core/bot_engine.py, exchange/binance_client.py, exchange/binance_ws.py, tests/test_coin_screener.py

## [2026-04-04 10:21 UTC]
Pending limit order system + dashboard UI: limit entry at best bid/ask, PendingOrder lifecycle, chart price levels, click-to-switch, SL/TP shift from fill price
Files: core/signal_generator.py, core/paper_trader.py, core/bot_engine.py, server/api.py, run_server.py, dashboard/src/types/index.ts, dashboard/src/store/tradingStore.ts, dashboard/src/hooks/useWebSocket.ts, dashboard/src/App.tsx, dashboard/src/components/CandleChart.tsx, dashboard/src/components/OpenPositions.tsx, dashboard/src/components/PendingLimitsTable.tsx, dashboard/src/components/ActiveSignals.tsx, dashboard/src/components/TopBar.tsx, dashboard/src/index.css, dashboard/vite.config.ts
