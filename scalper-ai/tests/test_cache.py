from __future__ import annotations

import pytest

from data.cache import MarketCache, MarketRegime, IndicatorSet


class TestMarketCache:
    def setup_method(self):
        self.cache = MarketCache()

    def test_init_symbol(self):
        self.cache.init_symbol("BTCUSDT")
        assert "BTCUSDT" in self.cache.klines
        assert self.cache.regime["BTCUSDT"] == MarketRegime.RANGING

    def test_init_symbol_idempotent(self):
        self.cache.init_symbol("ETHUSDT")
        self.cache.cvd["ETHUSDT"] = 42.0
        self.cache.init_symbol("ETHUSDT")
        assert self.cache.cvd["ETHUSDT"] == 42.0  # NOT reset

    def test_get_snapshot_default(self):
        self.cache.init_symbol("BTCUSDT")
        snap = self.cache.get_snapshot("BTCUSDT")
        assert snap.symbol == "BTCUSDT"
        assert snap.price == 0.0
        assert snap.cvd == 0.0

    def test_snapshot_after_data(self):
        self.cache.init_symbol("BTCUSDT")
        self.cache.cvd["BTCUSDT"] = 123.0
        snap = self.cache.get_snapshot("BTCUSDT")
        assert snap.cvd == 123.0


class TestMarketCacheAsync:
    @pytest.mark.asyncio
    async def test_update_kline(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        candle = {"t": 1000, "o": 50000.0, "h": 50100.0, "l": 49900.0, "c": 50050.0, "v": 10.0}
        await cache.update_kline("BTCUSDT", "1m", candle)
        assert len(cache.klines["BTCUSDT"]["1m"]) == 1

    @pytest.mark.asyncio
    async def test_update_book(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        await cache.update_book("BTCUSDT", 50000.0, 50001.0, 10.0, 5.0)
        assert cache.book_ticker["BTCUSDT"].bid == 50000.0
        assert cache.book_ticker["BTCUSDT"].ask == 50001.0
        assert cache.book_ticker["BTCUSDT"].ask_qty == 5.0

    @pytest.mark.asyncio
    async def test_update_agg_trade_cvd(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        await cache.update_agg_trade("BTCUSDT", {"q": "10", "m": False})   # buy → +10
        await cache.update_agg_trade("BTCUSDT", {"q": "3", "m": True})     # sell → -3
        assert cache.cvd["BTCUSDT"] == 7.0

    @pytest.mark.asyncio
    async def test_update_regime(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        await cache.update_regime("BTCUSDT", MarketRegime.TRENDING_BULL)
        assert cache.regime["BTCUSDT"] == MarketRegime.TRENDING_BULL

    @pytest.mark.asyncio
    async def test_rotate_1m_delta(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        # Accumulate some CVD
        await cache.update_agg_trade("BTCUSDT", {"q": "50", "m": False})   # +50
        await cache.update_agg_trade("BTCUSDT", {"q": "10", "m": True})    # -10 → total 40
        # Rotate: delta should be 40 (from start 0 to current 40)
        cache.rotate_1m_delta("BTCUSDT")
        assert cache.cvd_delta_1m["BTCUSDT"] == 40.0
        # volume_1m is the accumulated volume
        assert cache.volume_1m["BTCUSDT"] == 60.0  # 50 + 10
        # Add more CVD, rotate again
        await cache.update_agg_trade("BTCUSDT", {"q": "20", "m": False})   # +20 → total 60
        cache.rotate_1m_delta("BTCUSDT")
        assert cache.cvd_delta_1m["BTCUSDT"] == 20.0  # 60 - 40

    @pytest.mark.asyncio
    async def test_update_agg_trade_stores(self):
        cache = MarketCache()
        cache.init_symbol("BTCUSDT")
        trade = {"s": "BTCUSDT", "q": "1.0", "m": False}
        await cache.update_agg_trade("BTCUSDT", trade)
        assert len(cache.agg_trades["BTCUSDT"]) == 1
        assert cache.agg_trades["BTCUSDT"][0] == trade
