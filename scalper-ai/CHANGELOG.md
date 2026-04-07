
## [2026-04-06 21:38 UTC]
## [2026-04-06 21:53 UTC]
fix: depth stream - remove gap detection, apply absolute diff events safely
- LocalOrderBook: remove gap detection (depth events have absolute qty, safe to apply out-of-order)
- init_snapshot: apply all non-stale buffered events regardless of U vs lastUpdateId
- _fetch_depth_snapshot: seed cache immediately after snapshot (fixes depth_bids=0 on first tick)
- Remove _resync_depth + _depth_resyncing from bot_engine (no longer needed)
- WS-first then snapshot order preserved from previous commit


feat: replace depth20@100ms with full incremental order book (@depth@100ms)
- Add LocalOrderBook class (data/cache.py) with seq-gap detection + 200-event buffer
- REST /fapi/v1/depth?limit=500 snapshot fetched per symbol before WS start
- Diff events applied with Binance sync rules (U/u vs lastUpdateId)
- Auto re-sync on sequence gap via _fetch_depth_snapshot()
- wall_history now built from 500+ levels instead of 20 (genuine wall detection)
- Fix stale test: test_filters_extreme_volatility threshold 40->51%


## [2026-04-06 23:04 UTC]
feat: adaptive price bucketing in find_wall and _detect_wall (BUCKET_PCT=0.1%)
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
fix: remove regime direction block in CB — allows SHORT in BULL and LONG in BEAR
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
