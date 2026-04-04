from __future__ import annotations

from typing import Any

from data.cache import IndicatorSet, MarketRegime
from data.indicators import adx as calc_adx
from data.indicators import atr as calc_atr
from data.indicators import atr_percentile as calc_atr_pct
from data.indicators import ema as calc_ema
from data.indicators import rsi as calc_rsi
from data.indicators import vwap as calc_vwap

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
ADX_TRENDING = 25.0
ADX_TRANSITIONING = 20.0
ATR_LOW_VOL = 20.0
ATR_HIGH_VOL = 80.0


class RegimeClassifier:
    """Determines market regime from 5m candle data every 30s."""

    def classify(
        self, candles_5m: list[dict[str, Any]],
    ) -> tuple[MarketRegime, IndicatorSet]:
        indicators = self._compute_indicators(candles_5m)
        regime = self._determine_regime(indicators)
        return regime, indicators

    # -- private helpers (split for 50-line limit) --------------------------

    def _compute_indicators(
        self, candles: list[dict[str, Any]],
    ) -> IndicatorSet:
        if len(candles) < 16:
            return IndicatorSet()
        closes = [c["c"] for c in candles]
        adx_val = calc_adx(candles, 14)
        atr_val = calc_atr(candles, 14)
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        vwap_val = calc_vwap(candles)
        atr_pct = calc_atr_pct(candles, 14, 576)
        rsi_val = calc_rsi(closes, 14)
        return IndicatorSet(
            adx=adx_val,
            atr=atr_val,
            ema9=ema9,
            ema21=ema21,
            vwap=vwap_val,
            rsi=rsi_val,
            atr_percentile=atr_pct,
        )

    def _determine_regime(self, ind: IndicatorSet) -> MarketRegime:
        # ADX-based trend detection first (real trend overrides vol)
        if ind.adx > ADX_TRENDING:
            if ind.ema9 >= ind.ema21:
                return MarketRegime.TRENDING_BULL
            return MarketRegime.TRENDING_BEAR
        # Volatility override when no clear trend
        if ind.atr_percentile < ATR_LOW_VOL:
            return MarketRegime.LOW_VOL
        if ind.atr_percentile > ATR_HIGH_VOL:
            return MarketRegime.HIGH_VOL
        if ind.adx >= ADX_TRANSITIONING:
            return MarketRegime.RANGING  # TRANSITIONING maps to RANGING enum
        return MarketRegime.RANGING
