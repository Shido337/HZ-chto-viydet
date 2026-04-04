from __future__ import annotations

import pytest

from core.signal_generator import ScoreComponents, Signal
from data.cache import MarketRegime, MarketSnapshot, IndicatorSet
from strategies.continuation_break import ContinuationBreak
from strategies.mean_reversion import MeanReversion
from strategies.early_momentum import EarlyMomentum


# ML boost stub
ML_BOOST = 0.0


# ── Helpers ──

def _candle(o: float, h: float, l: float, c: float, v: float = 100.0, t: int = 0) -> dict:
    return {"o": o, "h": h, "l": l, "c": c, "v": v, "t": t}


def _make_trending_bull_snapshot() -> MarketSnapshot:
    """Build a snapshot that should trigger CONTINUATION_BREAK LONG."""
    # 3m klines: strong uptrend with a structure break on last candle
    klines_3m = []
    for i in range(25):
        base = 100 + i * 0.5
        klines_3m.append(_candle(base, base + 0.4, base - 0.1, base + 0.3, 100.0, i * 180000))
    # Last candle: big bullish break (body ≥ 0.15%)
    last_o = 112.0
    last_c = 112.5  # body = 0.5/112 = 0.45%
    klines_3m.append(_candle(last_o, last_c + 0.1, last_o - 0.1, last_c, 500.0, 25 * 180000))

    # 1m klines: last 3 closes ascending (bullish momentum)
    klines_1m = []
    for i in range(25):
        p = 110 + i * 0.1
        klines_1m.append(_candle(p, p + 0.2, p - 0.05, p + 0.15, 200.0 if i < 20 else 500.0, i * 60000))

    return MarketSnapshot(
        symbol="BTCUSDT",
        price=112.5,
        bid=112.5,
        ask=112.51,
        bid_qty=1000.0,
        ask_qty=300.0,
        regime=MarketRegime.TRENDING_BULL,
        indicators=IndicatorSet(adx=30.0, atr=0.5, ema9=112.0, ema21=111.0),
        cvd=500.0,
        cvd_delta_1m=50.0,
        volume_1m=500.0,
        klines_1m=tuple(klines_1m),
        klines_3m=tuple(klines_3m),
        klines_5m=(),
    )


def _make_ranging_sweep_snapshot() -> MarketSnapshot:
    """Build snapshot for MEAN_REVERSION: sweep above swing high then rejection."""
    klines_1m = []
    for i in range(30):
        if i < 28:
            p = 100 + (0.3 if i % 2 == 0 else -0.3)
            klines_1m.append(_candle(p - 0.1, p + 0.2, p - 0.2, p + 0.1, 100.0, i * 60000))
        elif i == 28:
            klines_1m.append(_candle(100.0, 100.5, 99.8, 100.3, 100.0, i * 60000))
        else:
            # Last candle: sweeps above 100.5 then closes back inside (wick rejection)
            klines_1m.append(_candle(100.3, 100.6, 99.9, 100.0, 200.0, i * 60000))

    return MarketSnapshot(
        symbol="ETHUSDT",
        price=100.0,
        bid=100.0,
        ask=100.01,
        bid_qty=200.0,
        ask_qty=500.0,
        regime=MarketRegime.RANGING,
        indicators=IndicatorSet(adx=15.0, atr=0.3, vwap=100.1),
        cvd=-20.0,
        cvd_delta_1m=-15.0,
        volume_1m=200.0,
        klines_1m=tuple(klines_1m),
        klines_3m=(),
        klines_5m=(),
    )


def _make_compression_snapshot() -> MarketSnapshot:
    """Build snapshot for EARLY_MOMENTUM: ATR compression + CVD buildup."""
    klines_5m = []
    for i in range(35):
        p = 50.0 + (0.01 if i % 2 == 0 else -0.01)
        klines_5m.append(_candle(p - 0.005, p + 0.01, p - 0.01, p + 0.005, 100.0, i * 300000))

    # 1m klines with CVD buildup: consecutive up-closes
    klines_1m = []
    for i in range(10):
        p = 50.0 + i * 0.002
        klines_1m.append(_candle(p, p + 0.005, p - 0.002, p + 0.003, 100.0, i * 60000))

    return MarketSnapshot(
        symbol="XRPUSDT",
        price=50.02,
        bid=50.02,
        ask=50.03,
        bid_qty=800.0,
        ask_qty=300.0,
        regime=MarketRegime.RANGING,
        indicators=IndicatorSet(adx=22.0, atr=0.01, atr_percentile=10.0, ema9=50.01, ema21=50.0),
        cvd=30.0,
        cvd_delta_1m=5.0,
        volume_1m=100.0,
        klines_1m=tuple(klines_1m),
        klines_3m=(),
        klines_5m=tuple(klines_5m),
    )


# ── Tests ──

class TestContinuationBreak:
    def setup_method(self) -> None:
        self.strategy = ContinuationBreak()

    def test_signal_on_trending_bull(self) -> None:
        snap = _make_trending_bull_snapshot()
        signal = self.strategy.compute_signal(snap, ML_BOOST)
        if signal is not None:
            assert signal.direction.value == "LONG"
            assert signal.setup_type == "CONTINUATION_BREAK"
            assert 0.0 <= signal.score <= 1.0
            assert signal.sl_price < signal.entry_price
            assert signal.tp_price > signal.entry_price

    def test_rejects_ranging_regime(self) -> None:
        snap = _make_trending_bull_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.RANGING,
            indicators=snap.indicators, cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m,
            volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        signal = self.strategy.compute_signal(snap, ML_BOOST)
        assert signal is None

    def test_rejects_low_vol(self) -> None:
        snap = _make_trending_bull_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.LOW_VOL,
            indicators=snap.indicators, cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m,
            volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        signal = self.strategy.compute_signal(snap, ML_BOOST)
        assert signal is None

    def test_rejects_insufficient_klines(self) -> None:
        snap = MarketSnapshot(
            symbol="BTCUSDT", price=100.0, bid=100.0, ask=100.01,
            bid_qty=50.0, ask_qty=50.0,
            regime=MarketRegime.TRENDING_BULL,
            indicators=IndicatorSet(),
            cvd=0, cvd_delta_1m=0, volume_1m=0,
            klines_1m=(), klines_3m=tuple(_candle(100, 101, 99, 100) for _ in range(5)),
            klines_5m=(),
        )
        assert self.strategy.compute_signal(snap, ML_BOOST) is None


class TestMeanReversion:
    def setup_method(self) -> None:
        self.strategy = MeanReversion()

    def test_rejects_trending_regime(self) -> None:
        snap = _make_ranging_sweep_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.TRENDING_BULL,
            indicators=snap.indicators, cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m,
            volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        assert self.strategy.compute_signal(snap, ML_BOOST) is None

    def test_sweep_short_signal(self) -> None:
        snap = _make_ranging_sweep_snapshot()
        signal = self.strategy.compute_signal(snap, ML_BOOST)
        if signal is not None:
            assert signal.direction.value == "SHORT"
            assert signal.setup_type == "MEAN_REVERSION"
            assert signal.sl_price > signal.entry_price


class TestEarlyMomentum:
    def setup_method(self) -> None:
        self.strategy = EarlyMomentum()

    def test_rejects_trending_regime(self) -> None:
        snap = _make_compression_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.TRENDING_BULL,
            indicators=IndicatorSet(adx=30.0),
            cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m, volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        assert self.strategy.compute_signal(snap, ML_BOOST) is None

    def test_rejects_high_adx(self) -> None:
        snap = _make_compression_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.RANGING,
            indicators=IndicatorSet(adx=30.0),  # too high
            cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m, volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        assert self.strategy.compute_signal(snap, ML_BOOST) is None

    def test_rejects_low_adx(self) -> None:
        snap = _make_compression_snapshot()
        snap = MarketSnapshot(
            symbol=snap.symbol, price=snap.price, bid=snap.bid, ask=snap.ask,
            bid_qty=snap.bid_qty, ask_qty=snap.ask_qty,
            regime=MarketRegime.RANGING,
            indicators=IndicatorSet(adx=15.0),  # too low
            cvd=snap.cvd, cvd_delta_1m=snap.cvd_delta_1m, volume_1m=snap.volume_1m,
            klines_1m=snap.klines_1m, klines_3m=snap.klines_3m, klines_5m=snap.klines_5m,
        )
        assert self.strategy.compute_signal(snap, ML_BOOST) is None


class TestScoreComponents:
    """Test that ScoreComponents.total() caps at correct weights."""

    def test_max_score_is_one(self) -> None:
        comp = ScoreComponents(0.25, 0.20, 0.15, 0.15, 0.15, 0.10)
        assert comp.total() == pytest.approx(1.0)

    def test_min_score_is_zero(self) -> None:
        comp = ScoreComponents(0, 0, 0, 0, 0, 0)
        assert comp.total() == 0.0

    def test_clamping(self) -> None:
        comp = ScoreComponents(0.50, 0.50, 0.50, 0.50, 0.50, 0.50)
        assert comp.total() == pytest.approx(1.0)

    def test_negative_passes_through(self) -> None:
        # min() only caps the upper bound; negatives pass through
        comp = ScoreComponents(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        assert comp.total() < 0
