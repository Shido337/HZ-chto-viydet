# SCALPER-AI CHANGELOG

## [2026-04-04 15:40 UTC]
Adaptive filter system: replace all hardcoded % thresholds with ATR-relative params. AdaptiveParams dataclass per-symbol, computed every 30s from regime + ATR percentile + learner feedback. Strategies use snap.adaptive for SL/TP/OB/volume/score. Paper trader trailing/BE now ATR-based. OnlineLearner score adjustment. Removed SL_WIDEN_HIGH_VOL hack. 10 trades: 4W/6L ~breakeven.
Files: data/cache.py, core/bot_engine.py, core/paper_trader.py, ml/online_learner.py, strategies/continuation_break.py, strategies/mean_reversion.py, strategies/early_momentum.py

## [2026-04-04 16:15 UTC]
Performance fix: CVD exit was killing winners (+$0.03 avg after 30s). Now requires 2min hold + 0.3% profit + 0.5×ATR profit. CB requires impulsive break (body≥0.5×ATR). Time stop 5→8min, extends to 12 if profitable. Trailing tighter in trends (0.2 ATR). Wider SL for trending (2.0×ATR). TP raised to 2.0 RR in trends.
Files: core/paper_trader.py, core/bot_engine.py, strategies/continuation_break.py

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

## [2026-04-04 10:22 UTC]
SL/TP scalping optimization: cap SL at 0.5%, ATR floor 0.75x, min SL 0.25%, TP cap for EM, breakeven accounts for fees, WS disconnect handling
Files: strategies/continuation_break.py, strategies/mean_reversion.py, strategies/early_momentum.py, core/paper_trader.py, server/api.py

## [2026-04-04 17:42 UTC]
Live trader ready: adaptive params, symbol precision, position recovery
Files: core/live_trader.py, exchange/order_executor.py, core/bot_engine.py, server/api.py
