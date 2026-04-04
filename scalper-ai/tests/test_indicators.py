from __future__ import annotations

import pytest

from data.indicators import (
    adx,
    atr,
    atr_percentile,
    bollinger_bands,
    cvd_from_trades,
    detect_swing_high,
    detect_swing_low,
    ema,
    order_book_imbalance,
    rsi,
    sma,
    volume_spike_ratio,
    vwap,
)


def _candle(h: float, l: float, c: float, o: float = 0.0, v: float = 100.0) -> dict:
    return {"o": o or l, "h": h, "l": l, "c": c, "v": v}


class TestEma:
    def test_basic(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ema(vals, 3)
        assert 3.5 < result < 5.0

    def test_single_value(self):
        assert ema([42.0], 10) == 42.0

    def test_empty(self):
        assert ema([], 10) == 0.0


class TestSma:
    def test_basic(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert sma(vals, 3) == 4.0  # avg of last 3

    def test_insufficient_data(self):
        assert sma([1.0, 2.0], 5) == 1.5


class TestATR:
    def test_returns_positive(self):
        candles = [
            _candle(h, l, c)
            for h, l, c in zip(
                [10.0, 11.0, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5, 15.0, 14.5,
                 16.0, 15.5, 17.0, 16.5, 18.0, 17.5],
                [9.0, 10.0, 11.0, 10.5, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5,
                 15.0, 14.5, 16.0, 15.5, 17.0, 16.5],
                [9.5, 10.5, 11.5, 11.0, 12.5, 12.0, 13.5, 13.0, 14.5, 14.0,
                 15.5, 15.0, 16.5, 16.0, 17.5, 17.0],
            )
        ]
        result = atr(candles, 14)
        assert result > 0

    def test_single_candle(self):
        assert atr([_candle(10.0, 9.0, 9.5)]) == 0.0


class TestADX:
    def test_returns_float(self):
        n = 30
        candles = [
            _candle(100.0 + i * 0.5, 99.0 + i * 0.5, 99.5 + i * 0.5)
            for i in range(n)
        ]
        result = adx(candles, 14)
        assert isinstance(result, float)


class TestRSI:
    def test_trending_up(self):
        closes = [float(i) for i in range(1, 30)]
        result = rsi(closes, 14)
        assert result > 70  # strongly bullish

    def test_trending_down(self):
        closes = [float(30 - i) for i in range(30)]
        result = rsi(closes, 14)
        assert result < 30  # strongly bearish

    def test_insufficient(self):
        assert rsi([1.0, 2.0], 14) == 50.0


class TestVWAP:
    def test_basic(self):
        candles = [
            _candle(10.0, 9.0, 9.5, v=100.0),
            _candle(11.0, 10.0, 10.5, v=200.0),
            _candle(12.0, 11.0, 11.5, v=150.0),
        ]
        result = vwap(candles)
        assert 9.0 < result < 12.0


class TestBollingerBands:
    def test_basic(self):
        closes = [float(i) for i in range(25)]
        upper, mid, lower = bollinger_bands(closes, 20, 2.0)
        assert upper > mid > lower


class TestCVD:
    def test_accumulation(self):
        trades = [
            {"q": "10", "m": False},   # buy +10
            {"q": "5", "m": True},     # sell -5
            {"q": "3", "m": False},    # buy +3
        ]
        assert cvd_from_trades(trades) == 8.0


class TestOrderBookImbalance:
    def test_balanced(self):
        assert order_book_imbalance(50.0, 50.0) == 0.5

    def test_bid_heavy(self):
        assert order_book_imbalance(80.0, 20.0) == 0.8

    def test_zero(self):
        assert order_book_imbalance(0.0, 0.0) == 0.5


class TestATRPercentile:
    def test_basic(self):
        candles = [_candle(float(i) + 1, float(i), float(i) + 0.5) for i in range(100)]
        current_atr = atr(candles[-15:], 14)
        result = atr_percentile(candles, 14, 100)
        assert 0.0 <= result <= 100.0

    def test_insufficient(self):
        assert atr_percentile([], 14) == 50.0


class TestSwingDetection:
    def test_swing_high(self):
        candles = [_candle(float(h), float(h) - 1, float(h) - 0.5)
                   for h in [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3]]
        result = detect_swing_high(candles, lookback=11)
        assert result == 5.0

    def test_swing_low(self):
        candles = [_candle(float(l) + 1, float(l), float(l) + 0.5)
                   for l in [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3]]
        result = detect_swing_low(candles, lookback=11)
        assert result == 1.0


class TestVolumeSpikeRatio:
    def test_spike(self):
        candles = [_candle(10.0, 9.0, 9.5, v=10.0)] * 20
        candles.append(_candle(10.0, 9.0, 9.5, v=50.0))
        assert volume_spike_ratio(candles) == 5.0

    def test_no_spike(self):
        candles = [_candle(10.0, 9.0, 9.5, v=10.0)] * 21
        assert volume_spike_ratio(candles) == pytest.approx(1.0)
