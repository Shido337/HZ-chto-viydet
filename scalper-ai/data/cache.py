from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums & lightweight data holders
# ---------------------------------------------------------------------------

class MarketRegime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    LOW_VOL = "LOW_VOL"
    HIGH_VOL = "HIGH_VOL"


@dataclass(frozen=True)
class BookTicker:
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    ts: float = 0.0


@dataclass(frozen=True)
class IndicatorSet:
    adx: float = 0.0
    atr: float = 0.0
    ema9: float = 0.0
    ema21: float = 0.0
    vwap: float = 0.0
    rsi: float = 50.0
    atr_percentile: float = 50.0


# ---------------------------------------------------------------------------
# Adaptive parameters — computed per-symbol from rolling market stats
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdaptiveParams:
    """ATR-relative thresholds that adapt to each symbol's volatility."""
    # Risk management (ATR-multiples)
    max_sl_atr: float = 2.0       # max SL = 2× ATR
    min_sl_atr: float = 0.5       # min SL = 0.5× ATR
    # TP ratios (adjusted by regime & performance)
    tp_rr: float = 1.5            # risk:reward
    # Trailing (ATR-relative)
    trail_activation_atr: float = 0.5  # activate at 0.5× ATR profit
    trail_distance_atr: float = 0.3    # trail distance = 0.3× ATR
    # Breakeven
    breakeven_trigger_atr: float = 0.4  # BE at 0.4× ATR
    # Score threshold (adjusted by learner)
    min_score: float = 0.65
    # Volume threshold (rolling-relative)
    volume_spike_min: float = 0.7
    # OB imbalance threshold
    ob_min: float = 0.55
    # ATR value for this symbol (absolute, for calculations)
    atr_value: float = 0.0
    # --- Entry filters (ATR-percentile driven) ---
    # CB: max ADX for clean retest
    cb_adx_max: float = 50.0
    # EM: ADX window for transitioning regime
    em_adx_low: float = 15.0
    em_adx_high: float = 35.0
    # EM: ATR compression percentile ceiling
    em_atr_compression_pct: float = 60.0
    # EM: consecutive 1m candles for CVD buildup
    em_cvd_bars: int = 2
    # MR: 1m candle window for sweep detection
    mr_sweep_window: int = 5


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable point-in-time copy handed to strategies."""
    symbol: str = ""
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    cvd: float = 0.0
    cvd_delta_1m: float = 0.0
    volume_1m: float = 0.0
    regime: MarketRegime = MarketRegime.RANGING
    indicators: IndicatorSet = field(default_factory=IndicatorSet)
    adaptive: AdaptiveParams = field(default_factory=AdaptiveParams)
    klines_1m: tuple[dict[str, Any], ...] = ()
    klines_3m: tuple[dict[str, Any], ...] = ()
    klines_5m: tuple[dict[str, Any], ...] = ()
    agg_trades: tuple[dict[str, Any], ...] = ()
    stale: bool = False
    ts: float = 0.0


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
MAX_KLINES = 500
MAX_AGG_TRADES = 1000


# ---------------------------------------------------------------------------
# MarketCache — single source of truth
# ---------------------------------------------------------------------------

class MarketCache:
    """Centralised mutable market state.  One asyncio.Lock per symbol."""

    def __init__(self) -> None:
        self.klines: dict[str, dict[str, deque[dict[str, Any]]]] = {}
        self.book_ticker: dict[str, BookTicker] = {}
        self.cvd: dict[str, float] = {}
        self.cvd_delta_1m: dict[str, float] = {}
        self.volume_1m: dict[str, float] = {}
        self.regime: dict[str, MarketRegime] = {}
        self.indicators: dict[str, IndicatorSet] = {}
        self.agg_trades: dict[str, deque[dict[str, Any]]] = {}
        self.adaptive_params: dict[str, AdaptiveParams] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._stale: dict[str, bool] = {}
        # CVD tracking for 1-minute rotation
        self._cvd_at_1m_start: dict[str, float] = {}
        self._vol_at_1m_start: dict[str, float] = {}
        self._volume_accum: dict[str, float] = {}

    # -- bootstrap ----------------------------------------------------------

    def init_symbol(self, symbol: str) -> None:
        """Idempotent — safe to call multiple times."""
        if symbol in self._locks:
            return
        self._locks[symbol] = asyncio.Lock()
        self.klines[symbol] = {
            "1m": deque(maxlen=MAX_KLINES),
            "3m": deque(maxlen=MAX_KLINES),
            "5m": deque(maxlen=MAX_KLINES),
        }
        self.book_ticker[symbol] = BookTicker()
        self.cvd[symbol] = 0.0
        self.cvd_delta_1m[symbol] = 0.0
        self.volume_1m[symbol] = 0.0
        self.regime[symbol] = MarketRegime.RANGING
        self.indicators[symbol] = IndicatorSet()
        self.adaptive_params[symbol] = AdaptiveParams()
        self.agg_trades[symbol] = deque(maxlen=MAX_AGG_TRADES)
        self._stale[symbol] = False
        self._cvd_at_1m_start[symbol] = 0.0
        self._vol_at_1m_start[symbol] = 0.0
        self._volume_accum[symbol] = 0.0

    def _lock(self, symbol: str) -> asyncio.Lock:
        lock = self._locks.get(symbol)
        if lock is None:
            self.init_symbol(symbol)
            lock = self._locks[symbol]
        return lock

    # -- atomic writers -----------------------------------------------------

    def load_klines(
        self, symbol: str, tf: str, candles: list[dict[str, Any]],
    ) -> None:
        """Bulk-load historical candles (call before WS starts)."""
        buf = self.klines[symbol][tf]
        for c in candles:
            buf.append(c)

    async def update_kline(
        self, symbol: str, tf: str, candle: dict[str, Any],
    ) -> None:
        async with self._lock(symbol):
            buf = self.klines[symbol][tf]
            if buf and buf[-1].get("t") == candle.get("t"):
                buf[-1] = candle  # update in-place
            else:
                buf.append(candle)
            self._stale[symbol] = False

    async def update_book(
        self, symbol: str, bid: float, ask: float,
        bid_qty: float = 0.0, ask_qty: float = 0.0,
    ) -> None:
        async with self._lock(symbol):
            self.book_ticker[symbol] = BookTicker(
                bid=bid, ask=ask, bid_qty=bid_qty,
                ask_qty=ask_qty, ts=time.time(),
            )
            self._stale[symbol] = False

    async def update_agg_trade(
        self, symbol: str, trade: dict[str, Any],
    ) -> None:
        """Lock-safe write of agg-trade + CVD accumulation."""
        async with self._lock(symbol):
            self.agg_trades[symbol].append(trade)
            qty = float(trade.get("q", 0))
            is_sell = trade.get("m", False)
            delta = -qty if is_sell else qty
            self.cvd[symbol] += delta
            self._volume_accum[symbol] += qty

    async def update_regime(
        self, symbol: str, regime: MarketRegime,
    ) -> None:
        async with self._lock(symbol):
            self.regime[symbol] = regime

    async def update_indicators(
        self, symbol: str, ind: IndicatorSet,
    ) -> None:
        async with self._lock(symbol):
            self.indicators[symbol] = ind

    async def update_adaptive(
        self, symbol: str, params: AdaptiveParams,
    ) -> None:
        async with self._lock(symbol):
            self.adaptive_params[symbol] = params

    def mark_stale(self, symbol: str) -> None:
        self._stale[symbol] = True

    # -- 1-minute CVD / volume rotation -------------------------------------

    def rotate_1m_delta(self, symbol: str) -> None:
        """Called on every 1m candle close.  Computes delta & volume."""
        current_cvd = self.cvd.get(symbol, 0.0)
        prev_cvd = self._cvd_at_1m_start.get(symbol, 0.0)
        self.cvd_delta_1m[symbol] = current_cvd - prev_cvd
        self._cvd_at_1m_start[symbol] = current_cvd

        self.volume_1m[symbol] = self._volume_accum.get(symbol, 0.0)
        self._volume_accum[symbol] = 0.0

    # -- immutable read -----------------------------------------------------

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        book = self.book_ticker.get(symbol, BookTicker())
        klines = self.klines.get(symbol, {})
        return MarketSnapshot(
            symbol=symbol,
            price=(book.bid + book.ask) / 2 if (book.bid and book.ask) else 0.0,
            bid=book.bid,
            ask=book.ask,
            bid_qty=book.bid_qty,
            ask_qty=book.ask_qty,
            cvd=self.cvd.get(symbol, 0.0),
            cvd_delta_1m=self.cvd_delta_1m.get(symbol, 0.0),
            volume_1m=self.volume_1m.get(symbol, 0.0),
            regime=self.regime.get(symbol, MarketRegime.RANGING),
            indicators=self.indicators.get(symbol, IndicatorSet()),
            adaptive=self.adaptive_params.get(symbol, AdaptiveParams()),
            klines_1m=tuple(klines.get("1m", deque())),
            klines_3m=tuple(klines.get("3m", deque())),
            klines_5m=tuple(klines.get("5m", deque())),
            agg_trades=tuple(self.agg_trades.get(symbol, deque())),
            stale=self._stale.get(symbol, False),
            ts=time.time(),
        )
