from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from data.indicators import bucket_levels, BUCKET_PCT


# ---------------------------------------------------------------------------
# Enums & lightweight data holders
# ---------------------------------------------------------------------------

class MarketRegime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    LOW_VOL = "LOW_VOL"
    HIGH_VOL = "HIGH_VOL"


WALL_MULTIPLIER = 5.0  # a level is a "wall" when its qty >= 5x median — must dominate the book


@dataclass(frozen=True)
class BookTicker:
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    ts: float = 0.0


@dataclass(frozen=True)
class WallSnapshot:
    """Detected wall levels at one point in time, built from @depth20 stream."""
    ts: float = 0.0
    bid_wall_price: float = 0.0
    bid_wall_qty: float = 0.0
    ask_wall_price: float = 0.0
    ask_wall_qty: float = 0.0
    mid_price: float = 0.0  # mid-price at snapshot time (for spoof detection)


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
    min_score: float = 0.55
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
    cvd_delta_20s: float = 0.0   # rolling delta over last 20 seconds (fast momentum)
    volume_1m: float = 0.0
    regime: MarketRegime = MarketRegime.RANGING
    indicators: IndicatorSet = field(default_factory=IndicatorSet)
    adaptive: AdaptiveParams = field(default_factory=AdaptiveParams)
    klines_1m: tuple[dict[str, Any], ...] = ()
    klines_3m: tuple[dict[str, Any], ...] = ()
    klines_5m: tuple[dict[str, Any], ...] = ()
    agg_trades: tuple[dict[str, Any], ...] = ()
    depth_bids: tuple[tuple[float, float], ...] = ()   # (price, qty) sorted bids from full order book
    depth_asks: tuple[tuple[float, float], ...] = ()   # (price, qty) sorted asks from full order book
    wall_history: tuple[WallSnapshot, ...] = ()        # recent depth wall snapshots (300 × 100ms = 30s)
    stale: bool = False
    ts: float = 0.0


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
MAX_KLINES = 500
MAX_AGG_TRADES = 1000


# ---------------------------------------------------------------------------
# LocalOrderBook — full incremental order book per symbol
# ---------------------------------------------------------------------------

class LocalOrderBook:
    """Full incremental order book maintained from @depth@100ms diff stream.

    Per Binance docs, each diff event carries ABSOLUTE quantities for each
    price level (not cumulative deltas), so applying events in order without
    strict sequence-ID validation is safe for wall detection purposes.

    Usage:
      1. Pre-create instance; events are buffered until init_snapshot is called.
      2. Call init_snapshot() with the REST /fapi/v1/depth response.
      3. Call apply_diff() for every incoming diff event.
    """

    MAX_BUFFER = 500  # 500 × 100ms = 50 s — plenty while awaiting snapshot

    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id: int = 0
        self.initialized: bool = False
        self._buffer: list[dict[str, Any]] = []

    def init_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Populate book from REST snapshot, then replay buffered diff events."""
        last_id: int = snapshot["lastUpdateId"]
        self.last_update_id = last_id
        self.bids = {float(p): float(q) for p, q in snapshot["bids"] if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in snapshot["asks"] if float(q) > 0}

        buffer = self._buffer[:]
        self._buffer = []
        self.initialized = True

        # Apply all buffered events that are newer than the snapshot.
        # Absolute quantities make this safe even if U > lastUpdateId + 1.
        for msg in buffer:
            if msg["u"] >= last_id + 1:
                self._apply_seq(msg)

    def apply_diff(self, msg: dict[str, Any]) -> None:
        """Apply an incoming diff event (buffer until snapshot is ready)."""
        if not self.initialized:
            if len(self._buffer) < self.MAX_BUFFER:
                self._buffer.append(msg)
            return

        if msg["u"] < self.last_update_id + 1:
            return  # older than snapshot, skip

        self._apply_seq(msg)

    def _apply_seq(self, msg: dict[str, Any]) -> None:
        """Update bids/asks from a single diff message (absolute quantities)."""
        for p, q in msg.get("b", []):
            price, qty = float(p), float(q)
            if qty == 0.0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty
        for p, q in msg.get("a", []):
            price, qty = float(p), float(q)
            if qty == 0.0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty
        self.last_update_id = msg["u"]

    def sorted_bids(self, limit: int = 500) -> list[tuple[float, float]]:
        return sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:limit]

    def sorted_asks(self, limit: int = 500) -> list[tuple[float, float]]:
        return sorted(self.asks.items(), key=lambda x: x[0])[:limit]


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
        # CVD rolling samples for short-term delta (20s window)
        # Each entry: (timestamp, cvd_value); throttled to 1 push per 0.5s
        self._cvd_samples: dict[str, deque[tuple[float, float]]] = {}
        self._cvd_last_sample_ts: dict[str, float] = {}
        # Depth (Level-2) data from @depth20 stream
        self.depth_bids: dict[str, list[tuple[float, float]]] = {}
        self.depth_asks: dict[str, list[tuple[float, float]]] = {}
        self.wall_history: dict[str, deque[WallSnapshot]] = {}

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
        self._cvd_samples[symbol] = deque(maxlen=120)  # 120 × 0.5s = 60s history
        self._cvd_last_sample_ts[symbol] = 0.0
        self.depth_bids[symbol] = []
        self.depth_asks[symbol] = []
        self.wall_history[symbol] = deque(maxlen=300)  # 300 × 100ms = 30s of wall history

    def _lock(self, symbol: str) -> asyncio.Lock:
        lock = self._locks.get(symbol)
        if lock is None:
            self.init_symbol(symbol)
            lock = self._locks[symbol]
        return lock

    # -- atomic writers -----------------------------------------------------

    @staticmethod
    def _detect_wall(
        levels: list[tuple[float, float]],
        mult: float = WALL_MULTIPLIER,
        mid_price: float = 0.0,
        max_dist_pct: float = 0.02,
        max_wall_ticks: int = 5,
    ) -> tuple[float, float]:
        """Returns (wall_price, wall_qty) or (0.0, 0.0) if no wall detected."""
        if mid_price > 0:
            lo = mid_price * (1.0 - max_dist_pct)
            hi = mid_price * (1.0 + max_dist_pct)
            levels = [(p, q) for p, q in levels if lo <= p <= hi]
        # Median-based wall detection (same logic as find_wall in indicators.py)
        raw = [(p, q) for p, q in levels if q > 0]
        if len(raw) < 3:
            return 0.0, 0.0
        sorted_qtys = sorted(q for _, q in raw)
        median_qty = sorted_qtys[len(sorted_qtys) // 2]
        if median_qty <= 0:
            return 0.0, 0.0
        threshold = median_qty * mult
        wall_ticks = [lv for lv in raw if lv[1] >= threshold]
        if not wall_ticks or len(wall_ticks) > max_wall_ticks:
            return 0.0, 0.0
        levels = bucket_levels(wall_ticks, BUCKET_PCT)
        if not levels:
            return 0.0, 0.0
        best_p, best_q = 0.0, 0.0
        for p, q in levels:
            if q > best_q:
                best_p, best_q = p, q
        return best_p, best_q

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

    async def update_depth(
        self, symbol: str,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
    ) -> None:
        """Store full order book snapshot and build wall history (from @depth@100ms diff stream)."""
        async with self._lock(symbol):
            self.depth_bids[symbol] = bids
            self.depth_asks[symbol] = asks
            # Compute mid from best bid/ask to apply 5% window for wall_history
            mid = 0.0
            if bids and asks:
                mid = (bids[0][0] + asks[0][0]) / 2.0
            elif bids:
                mid = bids[0][0]
            elif asks:
                mid = asks[0][0]
            bp, bq = self._detect_wall(bids, mid_price=mid)
            ap, aq = self._detect_wall(asks, mid_price=mid)
            self.wall_history[symbol].append(WallSnapshot(
                ts=time.time(),
                bid_wall_price=bp, bid_wall_qty=bq,
                ask_wall_price=ap, ask_wall_qty=aq,
                mid_price=mid,
            ))

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
            # Throttled CVD sample for 20s rolling delta (max 1 push per 0.5s)
            _now = time.time()
            if _now - self._cvd_last_sample_ts.get(symbol, 0.0) >= 0.5:
                self._cvd_samples[symbol].append((_now, self.cvd[symbol]))
                self._cvd_last_sample_ts[symbol] = _now

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

    # -- short-term CVD delta -----------------------------------------------

    def _compute_cvd_delta_20s(self, symbol: str) -> float:
        """Return CVD delta over the last 20 seconds from throttled samples."""
        samples = self._cvd_samples.get(symbol)
        if not samples:
            return 0.0
        now = time.time()
        cutoff = now - 20.0
        current_cvd = self.cvd.get(symbol, 0.0)
        # Find the oldest sample still within the 20s window
        baseline: float | None = None
        for ts, val in samples:
            if ts >= cutoff:
                baseline = val
                break  # deque is in append order (oldest first within window)
        if baseline is None:
            # All samples older than 20s — use the most recent one as baseline
            baseline = samples[-1][1] if samples else current_cvd
        return current_cvd - baseline

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
            cvd_delta_20s=self._compute_cvd_delta_20s(symbol),
            volume_1m=self.volume_1m.get(symbol, 0.0),
            regime=self.regime.get(symbol, MarketRegime.RANGING),
            indicators=self.indicators.get(symbol, IndicatorSet()),
            adaptive=self.adaptive_params.get(symbol, AdaptiveParams()),
            klines_1m=tuple(klines.get("1m", deque())),
            klines_3m=tuple(klines.get("3m", deque())),
            klines_5m=tuple(klines.get("5m", deque())),
            agg_trades=tuple(self.agg_trades.get(symbol, deque())),
            depth_bids=tuple(self.depth_bids.get(symbol, [])),
            depth_asks=tuple(self.depth_asks.get(symbol, [])),
            wall_history=tuple(self.wall_history.get(symbol, deque())),
            stale=self._stale.get(symbol, False),
            ts=time.time(),
        )
