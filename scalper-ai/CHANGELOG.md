# SCALPER-AI CHANGELOG

## [2026-04-06 02:30 UTC]
CB: BREAK_CLEARANCE_PCT 0.15%→0.05% — fix over-filtering of legitimate breaks
Root cause of missed BCH trade: DIAG showed "RETEST ob=0.88-0.95" for 7+ minutes
(01:53-02:04) but strategy silently rejected due to clearance check.
A break candle with body=0.55% (passes BODY_MIN_PCT=0.4%) that starts far below swing
can clear only 0.08-0.13% past it — was rejected by 0.15% threshold.
With BODY_MIN_PCT=0.4% in place, BODY is the real quality gate.
BREAK_CLEARANCE_PCT=0.15% was redundant AND over-restrictive.
Reduced to 0.05% (anti-degenerate only: prevents close=exact swing edge case).
Also fixed DIAG in bot_engine.py to include clearance check — previously DIAG
showed "RETEST" even when strategy was silently rejecting the break.
Files: strategies/continuation_break.py, core/bot_engine.py

## [2026-04-06 02:13 UTC]
CoinScreener: fix coin selection for real scalping quality
Problems found: 4-6 pump-and-dump coins (20-25% daily move) dominating watchlist
every cycle (STOUSDT, BRUSDT, RLSUSDT, NOMUSDT); these have no retest structure,
ADX 50-70+ blocks CB, MR impossible on trending coins; top liquid alts excluded
for wrong reasons ("too slow" — false at 25x leverage).
Changes:
1. MAX_PRICE_CHANGE_PCT: 30% → 12% — removes pump-and-dump coins
2. MIN_QUOTE_VOLUME_24H: $50M → $100M — removes micro-cap noise (unreliable OB)
3. MIN_TRADE_COUNT_24H: 100k → 150k — better microstructure signal quality
4. MAX_SYMBOLS: 12 → 10 — quality over quantity
5. EXCLUDED_SYMBOLS: removed SOLUSDT, DOGEUSDT, XRPUSDT, LINKUSDT — these have
   $500M-$5B volume, tight spreads, real swing structure, suit all 3 strategies
6. vol_score cap: $500M → $1B — better differentiation of major alts vs mid-caps
Result: 8 quality coins selected (vs 12 with 4+ pumps), pump coins eliminated
Files: core/coin_screener.py

## [2026-04-05 01:30 UTC]
EM market entry — limit orders incompatible with momentum setups:
1. EM now enters at market (ask for LONG, bid for SHORT) — instant fill
2. Other strategies (MR) keep limit entry for pullback fills
3. Fee accounting: EM entry = taker fee (0.04%), others = maker (0.02%)
4. Dashboard notified of immediate fill via _on_position_opened
Problem: EM signals were expiring because price moved away from limit
Files: core/paper_trader.py, core/bot_engine.py

## [2026-04-05 01:10 UTC]
Critical: Disable CB strategy + fix ML adaptive system:
1. CB DISABLED — 47 trades WR=23% PnL=-$5.67, toxic at ALL score levels (even 0.80+ = 17%WR)
2. ML learner: per-setup global tracking (was per-symbol only, never reached 10-sample threshold)
3. ML learner: fallback from per-(setup,symbol) to per-setup global for score adjustments
4. Adaptive: use max (most conservative) adjustment across enabled strategies
5. Stats/drift exclude global rollup keys to avoid double-counting
EM+MR alone: 40 trades, WR=45%, PnL=+$3.02
Files: core/bot_engine.py, ml/online_learner.py

## [2026-04-05 00:48 UTC]
Rollback aggressive exits — 5min MAX_HOLD made time_stop worse (4/8=50% of trades). Compromise:
1. MAX_HOLD_MINUTES: 5 → 6 — give trades more room
2. MAX_HOLD_IF_PROFIT: 8 → 10 — winners need time
3. STALE_EXIT_MINUTES: 4 → 5 — less aggressive stale cutting
Files: core/paper_trader.py

## [2026-04-05 00:10 UTC]
Aggressive exit tuning — time_stop was #1 PnL killer (-$3.28 from 10 trades, avg -$0.33):
1. MAX_HOLD_MINUTES: 8 → 5 — scalp trades that don't move in 5 min are dead
2. MAX_HOLD_IF_PROFIT: 10 → 8 — still generous for winners
3. STALE_EXIT_MINUTES: 6 → 4 — catch drifters before time_stop compounds loss
4. STALE_EXIT_DRAWDOWN: 0.4% → 0.3% — tighter threshold for early losers
Files: core/paper_trader.py

## [2026-04-04 23:25 UTC]
Performance tuning based on 69-trade analysis (CB 25%WR draining profits):
1. CB body requirement: 0.5× → 0.7× ATR — filters weak breaks (main loss source)
2. CB momentum bars: 2 → 3 — more confirmation before entering breakouts
3. Stale exit: close losing positions after 4min if down >0.2% — stops dead weight positions
4. Max hold if profit: 12min → 10min — less time for reversals to eat profits
Files: strategies/continuation_break.py, core/paper_trader.py

## [2026-04-04 23:12 UTC]
Fix late MR entry — two changes:
1. MR entry at 50% retracement between sweep_extreme and swing_level (was at swing_level = entering after bounce)
2. Paper trader limit: LONG uses min(bid, signal.entry), SHORT uses max(ask, signal.entry) — respects signal target instead of overriding with current bid/ask
Files: strategies/mean_reversion.py, core/paper_trader.py

## [2025-06-18 12:30 UTC]
Fix 3 paper trading bugs:
1. TP/SL exits now fill at their level price (not snap.price) — fixes phantom PnL mismatch where dashboard showed higher unrealized PnL
2. Mean Reversion entry uses swing level (bounce point) instead of last candle close — fixes LONG entries at candle tops
3. exit_price stored on Position dataclass and used in _persist_trade — DB records accurate exit prices
Files: core/paper_trader.py, strategies/mean_reversion.py, core/signal_generator.py, core/bot_engine.py

## [2025-06-18 12:00 UTC]
Fix empty chart on symbol switch: added REST endpoint GET /api/klines/{symbol} returning cached klines. CandleChart now fetches klines via REST fallback when store has no data (e.g. after symbol rotation or partial kline load failure). Added fitContent() after setData for proper auto-scroll.
Files: server/api.py, dashboard/src/components/CandleChart.tsx

## [2026-04-04 15:40 UTC]
Adaptive filter system: replace all hardcoded % thresholds with ATR-relative params. AdaptiveParams dataclass per-symbol, computed every 30s from regime + ATR percentile + learner feedback. Strategies use snap.adaptive for SL/TP/OB/volume/score. Paper trader trailing/BE now ATR-based. OnlineLearner score adjustment. Removed SL_WIDEN_HIGH_VOL hack. 10 trades: 4W/6L ~breakeven.
Files: data/cache.py, core/bot_engine.py, core/paper_trader.py, ml/online_learner.py, strategies/continuation_break.py, strategies/mean_reversion.py, strategies/early_momentum.py

## [2026-04-04 16:15 UTC]

## [2026-04-04 20:24 UTC]
Execution tuning to improve trade throughput and reduce premature technical exits:
1. Increased pending limit timeout to 60s (was 30s) so pullback entries have more time to fill
2. Relaxed stale exit trigger to 6 min and 0.4% drawdown (was 4 min and 0.2%)
Files: core/paper_trader.py

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

## [2026-04-04 17:51 UTC]
Fix live order lifecycle: fill verification, user data stream, throttled SL, exchange event sync
Files: core/live_trader.py, exchange/order_executor.py, exchange/binance_client.py, core/bot_engine.py

## [2026-04-04 18:27 UTC]
Exchange-native trailing stop: TRAILING_STOP_MARKET replaces software trailing/breakeven in LiveTrader
Files: core/live_trader.py, exchange/order_executor.py, core/signal_generator.py

## [2026-04-04 18:35 UTC]
2-stage trailing: BE-trail at entry + real trail upgrade on activation
Files: core/live_trader.py

## [2026-04-04 19:13 UTC]
Fix CB strategy: structural SL from prev candle, min/max risk guards 0.1-1.5%, swing lookback 8
Files: strategies/continuation_break.py

## [2026-04-04 19:15 UTC]
Switch workingType from MARK_PRICE to CONTRACT_PRICE (Last Price) for SL/TP/trailing
Files: exchange/order_executor.py

## [2026-04-04 23:09 UTC]
Fix empty chart: reset tracking refs on chart creation (StrictMode fix)
Files: dashboard/src/components/CandleChart.tsx

## [2026-04-04 23:25 UTC]
Redesign CB: break-and-retest (pullback entry at broken level) instead of chasing impulse. Re-enable CB strategy.
Files: strategies/continuation_break.py, core/bot_engine.py, tests/test_strategies.py

## [2026-04-04 23:39 UTC]
Fix chart: replace fragile prev-sym refs with data-key tracking (symbol+tf+firstTs+count). Proper cleanup on unmount. Cancel stale fetches.
Files: dashboard/src/components/CandleChart.tsx

## [2026-04-04 23:53 UTC]
Fix chart v3: render directly from REST fetch (no store round-trip), guard incremental updates via loadedKeyRef, autoSize:true
Files: dashboard/src/components/CandleChart.tsx

## [2026-04-05 00:03 UTC]
fix: chart explicit dims+ResizeObserver; CB lookback 10/prox 0.6%; update bot_engine CB diag
Files: dashboard/src/components/CandleChart.tsx, core/bot_engine.py, strategies/continuation_break.py


## [2026-04-05 00:07 UTC]
feat: signal arbitration — all strategies vote per symbol, highest score wins
Files: core/bot_engine.py


## [2026-04-05 00:16 UTC]
fix: CandleChart v4 - decouple fetch/render via state, eliminate async ref-check race
Files: dashboard/src/components/CandleChart.tsx


## [2026-04-05 00:24 UTC]
fix: disable CB (WR=23% -$7.41 over 53 trades); MR min SL 1xATR/0.3% floor; stale_exit 8min/0.5%
Files: core/bot_engine.py, strategies/mean_reversion.py, core/paper_trader.py


## [2026-04-05 08:14 UTC]
CB fix: SL hard cap 0.8%, ADX<=40, rejection candle, MIN_RR 1.5, BODY_MIN 0.1% � re-enable CB
Files: strategies/continuation_break.py, core/bot_engine.py

## [2026-04-05 08:19 UTC]
MR fix: CVD norm 1500 (was 5000), dynamic structure/vol score, sweep window 5 (was 3)
Files: strategies/mean_reversion.py

## [2026-04-05 08:23 UTC]
Dashboard fix: adaptive price formatting, score as %, clear chart on symbol change
Files: dashboard/src/types/index.ts, dashboard/src/components/OpenPositions.tsx, dashboard/src/components/ActiveSignals.tsx, dashboard/src/components/CandleChart.tsx

## [2026-04-05 08:26 UTC]
Dashboard: restore trade history from DB on WS init so stats survive page refresh
Files: dashboard/src/hooks/useWebSocket.ts

## [2026-04-05 08:39 UTC]
Session scope fix: track engine.started_at, filter restored trades by session start time
Files: core/bot_engine.py, server/api.py, dashboard/src/hooks/useWebSocket.ts, dashboard/src/types/index.ts

## [2026-04-05 10:12 UTC]
Fix started_at format: naive UTC string to match DB closed_at format (was ISO with tz suffix)
Files: core/bot_engine.py

## [2026-04-05 10:52 UTC]
Fix WS proxy, session filter date format, Performance Session/Total toggle
Files: scalper-ai/core/bot_engine.py, scalper-ai/dashboard/src/hooks/useWebSocket.ts, scalper-ai/dashboard/src/components/Performance.tsx, scalper-ai/dashboard/vite.config.ts

## [2026-04-05 11:42 UTC]
Relax strategy filters to fix signal starvation: CB ADX_MAX 40->55, EM ADX range 18-30->15-35, EM CVD bars 3->2, EM ATR compression 55->70
Files: strategies/continuation_break.py, strategies/early_momentum.py

## [2026-04-05 12:08 UTC]
Adaptive entry filters: move hardcoded ADX/ATR/CVD/sweep thresholds into AdaptiveParams, computed from atr_pct every 30s. Quiet market relaxes filters, active market tightens.
Files: data/cache.py, core/bot_engine.py, strategies/continuation_break.py, strategies/early_momentum.py, strategies/mean_reversion.py

## [2026-04-05 21:48 UTC]
Engine: LOW_VOL regime uses MR-only; PaperTrader: time_stop losers-only, stale_exit 4min
Files: scalper-ai/core/bot_engine.py, scalper-ai/core/paper_trader.py

## [2026-04-05 21:48 UTC]
Engine: LOW_VOL regime uses MR-only; PaperTrader: time_stop losers-only, stale_exit 4min
Files: scalper-ai/core/bot_engine.py, scalper-ai/core/paper_trader.py

## [2026-04-05 21:48 UTC]
Dashboard: CandleChart migrated to Zustand store-based rendering
Files: scalper-ai/dashboard/src/components/CandleChart.tsx

## [2026-04-05 21:49 UTC]
Strategies OFCS calibration: CB retest-entry architecture confirmed; EM proximity 0.1%, CVD 3-bar buildup, OB 65%; MR sweep range 0.05-0.30%%, CVD absorption + OB flip detection
Files: scalper-ai/strategies/continuation_break.py, scalper-ai/strategies/early_momentum.py, scalper-ai/strategies/mean_reversion.py

## [2026-04-05 22:36 UTC]
PaperTrader: per-setup hold caps CB=15min EM=6min MR=8min (was flat 6min for all)
Files: scalper-ai/core/paper_trader.py

## [2026-04-05 23:06 UTC]
CB: SWING_LOOKBACK 8->15 (45min structure), BODY_MIN_PCT 0.1%->0.4%, BREAK_CLEARANCE_PCT 0.15% (no false tick-breaks)
Files: scalper-ai/strategies/continuation_break.py
