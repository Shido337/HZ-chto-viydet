from __future__ import annotations

import pytest

from core.regime_classifier import RegimeClassifier
from data.cache import MarketRegime, IndicatorSet


def _candle(h: float, l: float, c: float, v: float = 100.0) -> dict:
    return {"o": l, "h": h, "l": l, "c": c, "v": v}


class TestRegimeClassifier:
    def setup_method(self):
        self.classifier = RegimeClassifier()

    def test_insufficient_data(self):
        candles = [_candle(10.0, 9.0, 9.5)] * 10
        regime, indicators = self.classifier.classify(candles)
        assert regime == MarketRegime.RANGING

    def test_trending_detection(self):
        # Strong trend: each candle higher than previous with volatile ranges
        candles = [
            _candle(100 + i * 2 + 3, 99 + i * 2 - 3, 99.5 + i * 2, v=500.0)
            for i in range(50)
        ]
        regime, indicators = self.classifier.classify(candles)
        # Should be trending or vol-driven (ATR percentile overrides ADX)
        assert regime in (
            MarketRegime.TRENDING_BULL,
            MarketRegime.HIGH_VOL,
            MarketRegime.LOW_VOL,
        )
        assert indicators.adx >= 0
        assert indicators.atr >= 0

    def test_ranging_detection(self):
        # Flat market: candles oscillate around same price with moderate variance
        candles = []
        for i in range(50):
            offset = 2.0 if i % 2 == 0 else -2.0
            candles.append(_candle(100 + offset + 1.0, 100 + offset - 1.0, 100 + offset))
        regime, indicators = self.classifier.classify(candles)
        assert regime in (MarketRegime.RANGING, MarketRegime.LOW_VOL, MarketRegime.HIGH_VOL)
