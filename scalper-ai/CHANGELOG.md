## [2026-04-06 21:38 UTC]

## [2026-04-06 21:53 UTC]

fix: depth stream - remove gap detection, apply absolute diff events safely

- LocalOrderBook: remove gap detection (depth events have absolute qty, safe to apply out-of-order)
- init_snapshot: apply all non-stale buffered events regardless of U vs lastUpdateId
- \_fetch_depth_snapshot: seed cache immediately after snapshot (fixes depth_bids=0 on first tick)
- Remove \_resync_depth + \_depth_resyncing from bot_engine (no longer needed)
- WS-first then snapshot order preserved from previous commit

feat: replace depth20@100ms with full incremental order book (@depth@100ms)

- Add LocalOrderBook class (data/cache.py) with seq-gap detection + 200-event buffer
- REST /fapi/v1/depth?limit=500 snapshot fetched per symbol before WS start
- Diff events applied with Binance sync rules (U/u vs lastUpdateId)
- Auto re-sync on sequence gap via \_fetch_depth_snapshot()
- wall_history now built from 500+ levels instead of 20 (genuine wall detection)
- Fix stale test: test_filters_extreme_volatility threshold 40->51%

## [2026-04-06 23:04 UTC]

feat: adaptive price bucketing in find_wall and \_detect_wall (BUCKET_PCT=0.1%)
Files: data/indicators.py, data/cache.py

## [2026-04-06 23:10 UTC]

fix: WallBounce absorption blocked in counter-trend regime; ABSORPTION_PCT 0.40->0.55
Files: strategies/wall_bounce.py

## [2026-04-06 23:16 UTC]

fix: stable log-scale bucketing; revert direction block in WallBounce
Files: data/indicators.py, data/cache.py, strategies/wall_bounce.py

## [2026-04-06 23:20 UTC]

fix: floor() in bucket_levels, BUCKET_PCT 0.001->0.003, dist 5%->3%, absorption dist cap 1.5%
Files: data/indicators.py, data/cache.py, strategies/wall_bounce.py

## [2026-04-06 23:31 UTC]

feat: cvd_delta_20s rolling 20s CVD; WallBounce uses 20s CVD instead of stale 1m
Files: data/cache.py, strategies/wall_bounce.py

## [2026-04-06 23:37 UTC]

fix: remove regime direction block in CB ï¿½ allows SHORT in BULL and LONG in BEAR
Files: strategies/continuation_break.py

## [2026-04-06 23:40 UTC]

screener: MAX_SYMBOLS 10->12
Files: core/coin_screener.py

## [2026-04-06 23:41 UTC]

screener: MAX_SYMBOLS 12->20
Files: core/coin_screener.py

## [2026-04-06 23:53 UTC]

fix: session reset on restart + signals expire after execution
Files: dashboard/src/hooks/useWebSocket.ts, core/bot_engine.py, server/api.py

## [2026-04-07 00:01 UTC]

wb: limit orders for bounce+absorption; absorption entry at wall level
Files: strategies/wall_bounce.py, core/paper_trader.py

## [2026-04-07 00:11 UTC]

fix: wall detection uses median-based threshold (not bucketed avg)
Files: data/indicators.py, data/cache.py

## [2026-04-07 00:17 UTC]

fix: reset signal cooldown on position close and pending expiry
Files: core/bot_engine.py

## [2026-04-07 00:26 UTC]

em: add trending impulse path (high ADX, no ATR compression required)
Files: strategies/early_momentum.py, core/bot_engine.py

## [2026-04-07 00:43 UTC]

fix: aggressively relax all strategy thresholds to generate actual signals
Files: strategies/early_momentum.py, strategies/continuation_break.py, strategies/mean_reversion.py, strategies/wall_bounce.py, strategies/base_strategy.py, data/cache.py, core/bot_engine.py

## [2026-04-07 00:52 UTC]

fix: widen WB SL floor (0.3%/0.5xATR), EM ATR compression 90-0.15x, CB retest 2.5%, EM-TREND cvd20s min=50
Files: strategies/wall_bounce.py, strategies/early_momentum.py, strategies/continuation_break.py, core/bot_engine.py

## [2026-04-07 01:01 UTC]

fix: clamp score components at 0, EM trending uses ADX for structure, remove CB rejection candle check
Files: core/signal_generator.py, strategies/early_momentum.py, strategies/continuation_break.py

## [2026-04-07 01:04 UTC]

fix: EM trending path only needs regime+CVD (remove OB and trend_alignment checks)
Files: strategies/early_momentum.py

## [2026-04-07 01:11 UTC]

fix: EM trending uses cvd_20s for scoring, WB pending timeout 180s
Files: strategies/early_momentum.py, core/paper_trader.py

## [2026-04-07 01:24 UTC]

tune: EM SL cap 1.5pct + 3-candle structure for trend, widen trailing in trends
Files: strategies/early_momentum.py, core/bot_engine.py, core/paper_trader.py

## [2026-04-07 01:33 UTC]

fix: EM SL floor 0.5pct to prevent noise stops
Files: strategies/early_momentum.py

## [2026-04-07 01:43 UTC]

tune: revert trailing to tight (0.3/0.25), raise min_score to 0.55
Files: core/bot_engine.py, strategies/base_strategy.py, data/cache.py

## [2026-04-07 01:54 UTC]

fix: global 0.8pct SL cap in paper_trader to limit max loss per trade
Files: core/paper_trader.py

## [2026-04-07 02:01 UTC]

fix: EM-TREND soft OB guard + price momentum confirmation to improve win rate
Files: strategies/early_momentum.py

## [2026-04-07 02:24 UTC]

tune: faster CVD exit (60s hold, 0.2pct min), EM hold 4min
Files: core/paper_trader.py

## [2026-04-07 02:56 UTC]

fix: 120s loss cooldown to prevent consecutive SL hit streaks on same symbol
Files: core/bot_engine.py

## [2026-04-07 03:34 UTC]

tune: CVD impulse 00 USD floor for EM-TREND to filter weak momentum
Files: strategies/early_momentum.py

## [2026-04-07 04:26 UTC]

tune: two-stage trailing - wider trail after 1x ATR profit for big runners
Files: core/paper_trader.py

## [2026-04-07 04:57 UTC]

fix: revert two-stage trail, add CVD warm-up guard, prevent trading with zero CVD
Files: core/paper_trader.py, core/bot_engine.py

## [2026-04-07 06:33 UTC]

tune: EM-TREND stricter filters ï¿½ ADX>35, CVD USD>2000, 2-candle momentum
Files: strategies/early_momentum.py

## [2026-04-07 06:53 UTC]

tune: tighter SL cap 0.5% + higher CVD exit min 0.4% ï¿½ fix loss/win ratio
Files: core/paper_trader.py

## [2026-04-07 07:25 UTC]

fix: progressive cooldown ï¿½ 2min/5min/10min after 1/2/3 consecutive losses per coin
Files: core/bot_engine.py

## [2026-04-07 07:44 UTC]

tune: WB bounce 1:1 TP ratio + disable EM-TREND (too many losers)
Files: strategies/wall_bounce.py, strategies/early_momentum.py

## [2026-04-07 08:01 UTC]

fix: recalculate TP when SL is capped ï¿½ maintain strategy RR ratio
Files: core/paper_trader.py

## [2026-04-07 08:23 UTC]

tune: re-enable EM-TREND strict, revert SL=0.8% + CVD exit 0.2% + WB original TP, keep TP recalc fix + progressive cooldown
Files: strategies/early_momentum.py, core/paper_trader.py, strategies/wall_bounce.py

## [2026-04-07 09:22 UTC]

feat: spoof wall detection ï¿½ flickering + qty-fade-on-approach filter, replaces round_number check
Files: data/indicators.py, data/cache.py, strategies/wall_bounce.py, core/bot_engine.py

## [2026-04-07 09:46 UTC]

fix: EM-TREND wall guard ï¿½ block SHORT into bid support, LONG into ask resistance within 1.5%
Files: strategies/early_momentum.py

## [2026-04-07 09:49 UTC]

feat: cancel WB pending limit when wall disappears ï¿½ no more trading without thesis
Files: core/paper_trader.py

## [2026-04-07 09:53 UTC]

feat: WB wall-gone SL tightens to wall edge ï¿½ thesis dead = immediate exit
Files: core/paper_trader.py

## [2026-04-07 09:56 UTC]

fix: EM-TREND pullback guard ï¿½ reject LONG when price >3% below recent 60min high (dead cat bounce filter)
Files: strategies/early_momentum.py, core/bot_engine.py

## [2026-04-07 09:58 UTC]

fix: WB bounce SL strictly behind wall (0.08%), not ATR-widened ï¿½ wall-gone tighten only for absorption
Files: strategies/wall_bounce.py, core/paper_trader.py, core/signal_generator.py

## [2026-04-07 10:10 UTC]

fix: WB min wall $50K USD filter ï¿½ skip noise walls, add USD to diagnostics
Files: strategies/wall_bounce.py, core/bot_engine.py

## [2026-04-07 10:21 UTC]

tune: WB MIN_WALL_USD 50K -> 20K ï¿½ less restrictive while still filtering noise
Files: strategies/wall_bounce.py

## [2026-04-07 10:25 UTC]

perf: disable CB (-12.5%), raise score 0.55->0.65, stale 0.5%->0.3% @ 2min, hold EM/WB 4->3min
Files: core/bot_engine.py, core/paper_trader.py

## [2026-04-07 10:27 UTC]

fix: skip stale_exit for WB ï¿½ SL is tight behind wall, let it play out
Files: core/paper_trader.py

## [2026-04-07 10:59 UTC]

feat: improved wall detection ï¿½ 8x median (was 5x), 2% range (was 3%), max 5 ticks concentration check
Files: data/indicators.py, data/cache.py

## [2026-04-07 11:02 UTC]

tune: remove MIN_WALL_USD filter ï¿½ 8x median multiplier is sufficient quality gate
Files: strategies/wall_bounce.py

## [2026-04-07 11:14 UTC]

tune: wall multiplier 8x->5x ï¿½ 8x caused instant wall-gone cancels, keep 2% dist + concentration check
Files: data/indicators.py, data/cache.py

## [2026-04-07 11:30 UTC]

fix: bounce scoring rework ï¿½ remove CVD/OB filters, score by wall proximity+touches+age. Bounce momentum starts AT wall not before.
Files: strategies/wall_bounce.py

## [2026-04-07 12:43 UTC]

fix: bounce regime guard ï¿½ block LONG in TRENDING_BEAR, SHORT in TRENDING_BULL. Trend pressure breaks walls in these regimes.
Files: strategies/wall_bounce.py

## [2026-04-07 12:51 UTC]

fix: absorption fires on eaten wall without CVD min; bounce blocked if wall >15% absorbed
Files: strategies/wall_bounce.py

## [2026-04-07 12:55 UTC]

fix: BOUNCE_MAX_ABS_PCT 15pct->5pct; wall eating >5% = breakout not bounce; min_hist=10 for faster detection
Files: strategies/wall_bounce.py

## [2026-04-07 12:57 UTC]

tune: BOUNCE_MAX_ABS_PCT 5pct->25pct
Files: strategies/wall_bounce.py

## [2026-04-07 12:59 UTC]

feat: WB bounce SL -> 3s cooldown for instant absorption re-entry on wall break, no loss counter increment
Files: core/bot_engine.py

## [2026-04-07 13:01 UTC]
feat: WB bounce early exit on wall_absorbed 30pct — detect breakout before SL, flip immediately
Files: core/paper_trader.py, core/bot_engine.py

## [2026-04-07 13:27 UTC]
fix: wall_absorbed reversal signal + cooldown math + Signal.timestamp->PendingOrder.created_at
Files: core/bot_engine.py, core/paper_trader.py

## [2026-04-07 14:10 UTC]
fix: EM cvd_buildup validates real CVD sign; trending path blocks opposite 1m CVD
Files: strategies/early_momentum.py

## [2026-04-07 14:20 UTC]
fix: bounce market fill instead of limit — price never drops to limit when trending
Files: strategies/wall_bounce.py, core/paper_trader.py

## [2026-04-07 14:30 UTC]
tune: bounce BOUNCE_DIST_PCT 1.2%->0.5% — tighter entry near wall, smaller SL
Files: strategies/wall_bounce.py

## [2026-04-07 14:33 UTC]
feat: bounce CVD-based market/limit split — going away=market, toward wall=limit
Files: strategies/wall_bounce.py, core/paper_trader.py, core/bot_engine.py

## [2026-04-07 15:03 UTC]
fix: bounce sl_hit also triggers reversal signal (same as wall_absorbed), CVD-gated
Files: core/bot_engine.py

## [2026-04-07 15:12 UTC]
fix: wall-gone cancelled orders get 15s cooldown, not instant retry
Files: core/bot_engine.py, core/paper_trader.py

## [2026-04-07 15:36 UTC]
fix: cache.adaptive_params.get() instead of nonexistent get_adaptive_params()
Files: core/bot_engine.py

## [2026-04-07 15:42 UTC]
feat: reversal uses spoof+absorption detection instead of CVD gate
Files: core/bot_engine.py

## [2026-04-07 16:12 UTC]
fix: raise absorption threshold 15pct to 50pct for reversal
Files: core/bot_engine.py
