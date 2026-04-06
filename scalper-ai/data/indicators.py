from __future__ import annotations

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

def find_wall(
    levels: tuple | list, multiplier: float = 5.0,
) -> tuple[float, float] | None:
    """Detect dominant order wall in a sequence of (price, qty) depth levels.

    Returns (wall_price, wall_qty) for the largest level that is ≥multiplier×avg,
    or None if no such level exists.
    """
    if len(levels) < 5:
        return None
    qtys = [q for _, q in levels if q > 0]
    if not qtys:
        return None
    avg = sum(qtys) / len(qtys)
    best: tuple[float, float] | None = None
    for price, qty in levels:
        if qty >= avg * multiplier:
            if best is None or qty > best[1]:
                best = (price, qty)
    return best


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


def wall_is_eaten(
    history: tuple,
    wall_price: float,
    side: str,
    match_pct: float = 0.001,
    min_readings: int = 10,
    gradual_threshold: float = 0.5,
) -> bool:
    """Distinguish real eating (gradual decline) from spoofing (sudden removal).

    A wall is considered *eaten* when its qty decreased through at least
    ``min_readings`` intermediate readings with a mostly monotonic decline.
    If the wall qty drops by >50 % between consecutive snapshots at any point
    and that single drop accounts for more than *gradual_threshold* of the
    total decline, we classify it as *removed* (spoof / pull).

    Returns True  → wall eaten gradually (real absorption).
    Returns False → wall removed suddenly (spoof) or insufficient data.
    """
    if len(history) < min_readings:
        return False
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
    if len(qtys) < min_readings:
        return False
    peak = max(qtys)
    if peak <= 0:
        return False
    total_decline = peak - qtys[-1]
    if total_decline <= 0:
        return False  # not declining
    # Find the largest single-step drop
    max_single_drop = 0.0
    for i in range(1, len(qtys)):
        drop = qtys[i - 1] - qtys[i]
        if drop > max_single_drop:
            max_single_drop = drop
    # If one single drop is >50% of total decline → it's a pull, not eating
    if max_single_drop / total_decline > gradual_threshold:
        return False
    return True
