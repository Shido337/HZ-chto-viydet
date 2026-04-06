
## [2026-04-06 21:38 UTC]
feat: replace depth20@100ms with full incremental order book (@depth@100ms)
- Add LocalOrderBook class (data/cache.py) with seq-gap detection + 200-event buffer
- REST /fapi/v1/depth?limit=500 snapshot fetched per symbol before WS start
- Diff events applied with Binance sync rules (U/u vs lastUpdateId)
- Auto re-sync on sequence gap via _fetch_depth_snapshot()
- wall_history now built from 500+ levels instead of 20 (genuine wall detection)
- Fix stale test: test_filters_extreme_volatility threshold 40->51%

