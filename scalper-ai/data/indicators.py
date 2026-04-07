from __future__ import annotations

import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

def ema(values: list[float], period: int) -> float:
    """Exponential moving average of last *period* values."""
    if len(values) < period:
        return values[-1] if values else 0.0
    arr = np.array(values[-period * 3 :], dtype=np.float64)
    alpha = 2.0 / (period + 1)
    result = arr[0]
    for v in arr[1:]:
        result = alpha * v + (1 - alpha) * result
    return float(result)


def sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return np.mean(values).item() if values else 0.0
    return float(np.mean(values[-period:]))


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------

def atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        pc = candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return float(ema(trs, period))


# ---------------------------------------------------------------------------
# ADX (Average Directional Index)
# ---------------------------------------------------------------------------

def adx(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 2:
        return 0.0
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, len(candles)):
        h, l = candles[i]["h"], candles[i]["l"]
        ph, pl = candles[i - 1]["h"], candles[i - 1]["l"]
        pc = candles[i - 1]["c"]
        up = h - ph
        down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr_val = ema(trs, period)
    if atr_val == 0:
        return 0.0
    plus_di = 100.0 * ema(plus_dm, period) / atr_val
    minus_di = 100.0 * ema(minus_dm, period) / atr_val
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    dx = 100.0 * abs(plus_di - minus_di) / di_sum
    return dx


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    deltas = np.diff(values[-period - 1 :])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains)) if len(gains) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# ---------------------------------------------------------------------------
# VWAP (from candles — approximate)
# ---------------------------------------------------------------------------

def vwap(candles: list[dict[str, Any]]) -> float:
    if not candles:
        return 0.0
    cum_pv = 0.0
    cum_v = 0.0
    for c in candles:
        typical = (c["h"] + c["l"] + c["c"]) / 3
        vol = c.get("v", 0.0)
        cum_pv += typical * vol
        cum_v += vol
    if cum_v == 0:
        return 0.0
    return cum_pv / cum_v


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bollinger_bands(
    values: list[float], period: int = 20, num_std: float = 2.0,
) -> tuple[float, float, float]:
    """Returns (upper, middle, lower)."""
    if len(values) < period:
        m = values[-1] if values else 0.0
        return m, m, m
    arr = np.array(values[-period:], dtype=np.float64)
    middle = float(np.mean(arr))
    std = float(np.std(arr))
    return middle + num_std * std, middle, middle - num_std * std


# ---------------------------------------------------------------------------
# CVD from aggTrades
# ---------------------------------------------------------------------------

def cvd_from_trades(trades: list[dict[str, Any]]) -> float:
    total = 0.0
    for t in trades:
        qty = float(t.get("q", 0))
        if t.get("m", False):
            total -= qty
        else:
            total += qty
    return total


# ---------------------------------------------------------------------------
# Order Book Imbalance
# ---------------------------------------------------------------------------

def order_book_imbalance(bid_qty: float, ask_qty: float) -> float:
    """Returns bid ratio 0.0–1.0.  0.5 = neutral."""
    total = bid_qty + ask_qty
    if total == 0:
        return 0.5
    return bid_qty / total


# ---------------------------------------------------------------------------
# ATR Percentile (rolling)
# ---------------------------------------------------------------------------

def atr_percentile(
    candles: list[dict[str, Any]], period: int = 14, window: int = 576,
) -> float:
    """Percentile of current ATR in last *window* ATR values.
    576 5m-candles ≈ 48 hours.
    """
    if len(candles) < period + 2:
        return 50.0
    atrs: list[float] = []
    end = len(candles)
    start = max(period + 1, end - window)
    for i in range(start, end):
        slice_ = candles[max(0, i - period - 1) : i + 1]
        atrs.append(atr(slice_, period))
    if not atrs:
        return 50.0
    current = atrs[-1]
    below = sum(1 for a in atrs if a < current)
    return 100.0 * below / len(atrs)


# ---------------------------------------------------------------------------
# Structure detection helpers
# ---------------------------------------------------------------------------

def detect_swing_high(candles: list[dict[str, Any]], lookback: int = 10) -> float:
    if len(candles) < lookback:
        return 0.0
    return max(c["h"] for c in candles[-lookback:])


def detect_swing_low(candles: list[dict[str, Any]], lookback: int = 10) -> float:
    if len(candles) < lookback:
        return 0.0
    return min(c["l"] for c in candles[-lookback:])


# ---------------------------------------------------------------------------
# Volume helpers
# ---------------------------------------------------------------------------

def volume_spike_ratio(candles: list[dict[str, Any]], period: int = 20) -> float:
    """Current 1m volume / SMA of last *period* volumes."""
    if len(candles) < 2:
        return 0.0
    vols = [c.get("v", 0.0) for c in candles]
    current = vols[-1]
    avg = sma(vols[:-1], period)
    if avg == 0:
        return 0.0
    return current / avg


# ---------------------------------------------------------------------------
# Order-book wall helpers (for WallBounce strategy)
# ---------------------------------------------------------------------------

# Adaptive bucketing: merge price levels within this fraction of price.
# 0.003 = 0.3% → at MMTUSDT@0.12 → 0.00036/bucket ≈ 3-4 ticks merged.
BUCKET_PCT = 0.003


def bucket_levels(
    levels: list[tuple[float, float]],
    bucket_pct: float = BUCKET_PCT,
) -> list[tuple[float, float]]:
    """Aggregate nearby price levels using log-scale stable bucketing.

    Uses floor(log_{1+bucket_pct}(price)) as the bucket index.  This gives
    stable integer IDs regardless of the current mid_price — levels within
    *bucket_pct* of each other always land in the same bucket every tick.
    Quantities are summed; representative price = highest-qty tick in bucket.
    """
    if bucket_pct <= 0 or not levels:
        return list(levels)
    log_step = math.log(1.0 + bucket_pct)
    totals: dict[int, float] = {}
    best: dict[int, tuple[float, float]] = {}  # idx → (best_qty, best_price)
    for price, qty in levels:
        if price <= 0:
            continue
        idx = math.floor(math.log(price) / log_step)
        totals[idx] = totals.get(idx, 0.0) + qty
        prev_best = best.get(idx, (0.0, price))
        if qty > prev_best[0]:
            best[idx] = (qty, price)
    return [(best[i][1], totals[i]) for i in sorted(totals)]


def find_wall(
    levels: tuple | list,
    multiplier: float = 5.0,
    mid_price: float = 0.0,
    max_dist_pct: float = 0.03,
    bucket_pct: float = BUCKET_PCT,
) -> tuple[float, float] | None:
    """Detect dominant order wall in a sequence of (price, qty) depth levels.

    Uses median-based threshold on raw ticks so a concentrated wall level
    (e.g. 369K vs ~15K neighbours) is not diluted by bucketing.
    Algorithm:
      1. Filter ticks to price window.
      2. Compute median tick qty as robust baseline.
      3. Keep only ticks where qty >= median * multiplier.
      4. Aggregate adjacent wall ticks into log-scale buckets.
      5. Return the heaviest bucket.
    """
    if mid_price > 0:
        lo = mid_price * (1.0 - max_dist_pct)
        hi = mid_price * (1.0 + max_dist_pct)
        levels = [(p, q) for p, q in levels if lo <= p <= hi]
    raw = [(p, q) for p, q in levels if q > 0]
    if len(raw) < 3:
        return None
    sorted_qtys = sorted(q for _, q in raw)
    median_qty = sorted_qtys[len(sorted_qtys) // 2]
    if median_qty <= 0:
        return None
    threshold = median_qty * multiplier
    # Keep only dominant ticks (potential wall ticks)
    wall_ticks = [(p, q) for p, q in raw if q >= threshold]
    if not wall_ticks:
        return None
    # Aggregate nearby wall ticks into buckets (wall spread across 2-3 adjacent ticks)
    aggregated = bucket_levels(wall_ticks, bucket_pct)
    if not aggregated:
        return None
    return max(aggregated, key=lambda x: x[1])


def wall_absorption_pct(
    history: tuple,
    wall_price: float,
    side: str,
    match_pct: float = 0.001,
    min_hist: int = 50,
) -> float:
    """Return fraction [0.0–1.0] of wall qty that has been absorbed.

    Compares the peak observed wall qty at *wall_price* against the most recent
    reading.  Returns 0.0 when there is insufficient history.

    Args:
        history: tuple of WallSnapshot objects from MarketSnapshot.wall_history.
        wall_price: reference price of the wall level.
        side: "bid" or "ask".
        match_pct: price tolerance to consider a snapshot matching wall_price.
        min_hist: minimum snapshots required before producing a result.
    """
    if len(history) < min_hist:
        return 0.0
    thresh = wall_price * match_pct
    if side == "ask":
        qtys = [
            s.ask_wall_qty for s in history
            if abs(s.ask_wall_price - wall_price) <= thresh and s.ask_wall_qty > 0
        ]
    else:
        qtys = [
            s.bid_wall_qty for s in history
            if abs(s.bid_wall_price - wall_price) <= thresh and s.bid_wall_qty > 0
        ]
    if len(qtys) < 20:
        return 0.0
    max_qty = max(qtys)
    if max_qty <= 0:
        return 0.0
    return max(0.0, (max_qty - qtys[-1]) / max_qty)


def wall_stable(
    history: tuple,
    wall_price: float,
    side: str,
    min_seconds: float = 5.0,
    match_pct: float = 0.001,
) -> bool:
    """True if the wall at *wall_price* has been continuously present for at
    least *min_seconds*.

    Spoof walls appear and disappear in <1 second.  Real walls sit for many
    seconds or minutes.  We require the wall to appear in consecutive snapshots
    covering ≥ min_seconds of history (snapshots are 100 ms apart).

    Args:
        history:      tuple of WallSnapshot from MarketSnapshot.wall_history.
        wall_price:   price level of the wall to check.
        side:         "bid" or "ask".
        min_seconds:  minimum wall age in seconds (default 5 s = 50 snapshots).
        match_pct:    price tolerance for matching snapshots to wall_price.
    """
    if not history:
        return False
    min_snaps = int(min_seconds / 0.1)   # 100 ms per snapshot
    thresh = wall_price * match_pct
    # Walk backwards through history; count unbroken streak at this level
    streak = 0
    for snap in reversed(history):
        if side == "ask":
            present = abs(snap.ask_wall_price - wall_price) <= thresh and snap.ask_wall_qty > 0
        else:
            present = abs(snap.bid_wall_price - wall_price) <= thresh and snap.bid_wall_qty > 0
        if present:
            streak += 1
        else:
            break   # first gap → streak is over
    return streak >= min_snaps


def wall_on_round_number(price: float, tolerance: float = 0.001) -> bool:
    """True if *price* sits on a psychologically round level (real wall signal).

    CScalp rule: real walls appear at round numbers (85000, 49000, 22500).
    Spoofer walls appear at irregular prices (84783, 131.37).

    Algorithm: only coarse sub-divisions of the order of magnitude are checked
    (divisors 1, 2, 4, 5, 10, 20).  The finest unit for BTC ~85 000 is 500;
    for SOL ~130 it is 5.  Finer grids produce false positives because nearly
    any price falls within 0.1 % of some multiple.

    Examples:
        85000 → True  (85 × 1000)
        84500 → True  (169 × 500)
        84783 → False (nearest 500-multiple is 85000, 0.26 % away)
        130.0 → True  (13 × 10)
        131.37 → False
    """
    if price <= 0:
        return False
    magnitude = 10 ** math.floor(math.log10(price))
    for divisor in (1, 2, 4, 5, 10, 20):
        unit = magnitude / divisor
        nearest = round(price / unit) * unit
        if abs(price - nearest) / price <= tolerance:
            return True
    return False


def count_level_touches(
    klines: list[dict[str, Any]],
    level: float,
    touch_zone_pct: float = 0.002,
    lookback: int = 200,
) -> int:
    """Count distinct candle touches of *level* in recent klines.

    CScalp rule: ≥2 confirmed touches = strong level worth trading.
    A single untested level is weak — it may not hold.

    A touch is counted when a candle's high or low enters the zone
    [level×(1−touch_zone_pct), level×(1+touch_zone_pct)].
    Consecutive candles in the same zone count as ONE touch.

    Args:
        klines:         list of OHLCV dicts with keys 'h' and 'l'.
        level:          price level to test.
        touch_zone_pct: ±0.2 % tolerance (default).
        lookback:       number of most-recent candles to inspect.
    """
    if not klines or level <= 0:
        return 0
    lo = level * (1.0 - touch_zone_pct)
    hi = level * (1.0 + touch_zone_pct)
    recent = klines[-lookback:]
    touches = 0
    in_zone = False
    for c in recent:
        hit = c["h"] >= lo and c["l"] <= hi
        if hit and not in_zone:
            touches += 1
        in_zone = hit
    return touches


def vei(candles: list[dict[str, Any]], short: int = 10, long: int = 50) -> float:
    """Volatility Expansion Index = ATR(short) / ATR(long).

    From Reddit /r/algotrading — filters unstable market conditions.

    VEI < 1.0  → stable / normal  → countertrend (bounce) setups work well
    VEI > 1.2  → volatile / noisy → reduce size or skip bounce entries

    Args:
        candles: list of OHLCV dicts.
        short:   fast ATR period (default 10).
        long:    slow ATR period (default 50).
    """
    if len(candles) < long + 1:
        return 1.0   # insufficient data → neutral
    atr_short = atr(candles, short)
    atr_long = atr(candles, long)
    if atr_long <= 0:
        return 1.0
    return atr_short / atr_long
