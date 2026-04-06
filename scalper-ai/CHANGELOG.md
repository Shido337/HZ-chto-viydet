
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
