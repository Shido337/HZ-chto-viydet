from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Screening thresholds
# ---------------------------------------------------------------------------
MIN_QUOTE_VOLUME_24H = 50_000_000.0    # $50M min 24h USDT volume (lowered for mid-caps with walls)
MAX_SPREAD_PCT = 0.0005                  # 0.05% max bid-ask spread
MIN_PRICE_CHANGE_PCT = 1.0              # min 1.0% daily move (abs) — 1.5% cut BTC/ETH on flat days
MAX_PRICE_CHANGE_PCT = 12.0             # max 12% daily move (was 30% — kills pump-and-dump coins)
MIN_TRADE_COUNT_24H = 100_000           # min 100k trades (lowered for mid-caps)
MAX_SYMBOLS = 20                        # top 20 — BTC/ETH added back, wider coverage
SCREENER_INTERVAL = 300                 # re-screen every 5 minutes
DEPTH_WALL_MULT = 5.0                   # level ≥5× avg = wall (for screening, relaxed vs live 8×)

# Coins to always exclude:
# BTC/ETH — $30-50B daily volume, walls are institutional and get absorbed silently.
# No clean WB bounce at our scale. Too liquid for proportional wall detection.
# BNB — Binance-native, unusual book dynamics.
EXCLUDED_SYMBOLS: set[str] = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "ADAUSDT", "DOTUSDT",
}


@dataclass
class CoinScore:
    """Screening metrics for one symbol."""
    symbol: str
    quote_volume: float       # USDT 24h volume
    spread_pct: float         # bid-ask spread %
    price_change_pct: float   # abs 24h price change %
    trade_count: int          # 24h trade count
    depth_score: float        # order book wall quality [0-1]
    composite_score: float    # final ranking score


def _depth_imbalance_score(depth: dict[str, Any]) -> float:
    """Score how "wall-rich" the depth20 snapshot is.

    Returns 0-1: higher = more dominant walls (better for WB strategy).
    """
    bids = depth.get("bids", [])
    asks = depth.get("asks", [])
    if len(bids) < 5 or len(asks) < 5:
        return 0.0
    bid_qtys = [float(b[1]) for b in bids if float(b[1]) > 0]
    ask_qtys = [float(a[1]) for a in asks if float(a[1]) > 0]
    if not bid_qtys or not ask_qtys:
        return 0.0
    # Max-to-avg ratio: how dominant the biggest level is
    bid_avg = sum(bid_qtys) / len(bid_qtys)
    ask_avg = sum(ask_qtys) / len(ask_qtys)
    bid_ratio = max(bid_qtys) / bid_avg if bid_avg > 0 else 0
    ask_ratio = max(ask_qtys) / ask_avg if ask_avg > 0 else 0
    best_ratio = max(bid_ratio, ask_ratio)
    # Normalize: 5× = 0.5, 10× = 0.8, 20×+ = 1.0
    if best_ratio < 2.0:
        return 0.0
    return min((best_ratio - 2.0) / 18.0, 1.0)


class CoinScreener:
    """Dynamic coin selection based on volume, spread, volatility and depth."""

    def __init__(self) -> None:
        self._perpetual_symbols: set[str] = set()
        self._client: Any = None  # BinanceClient, set by bot_engine

    def set_perpetual_symbols(self, symbols: list[dict[str, Any]]) -> None:
        """Cache valid PERPETUAL USDT-M symbol names from exchangeInfo."""
        self._perpetual_symbols = {s.get("symbol", "") for s in symbols}
        logger.info(f"CoinScreener: {len(self._perpetual_symbols)} perpetual pairs loaded")

    async def screen(
        self,
        tickers_24hr: list[dict[str, Any]],
        book_tickers: list[dict[str, Any]],
    ) -> list[str]:
        """Screen and rank coins. Returns sorted list of top symbol names."""
        # Build book ticker lookup
        book_map: dict[str, dict[str, Any]] = {}
        for bt in book_tickers:
            sym = bt.get("symbol", "")
            if sym:
                book_map[sym] = bt

        candidates: list[CoinScore] = []

        for tk in tickers_24hr:
            symbol = tk.get("symbol", "")

            # --- basic filters ---
            if not symbol.endswith("USDT"):
                continue
            if symbol in EXCLUDED_SYMBOLS:
                continue
            if self._perpetual_symbols and symbol not in self._perpetual_symbols:
                continue

            # --- extract metrics ---
            quote_volume = float(tk.get("quoteVolume", 0))
            if quote_volume < MIN_QUOTE_VOLUME_24H:
                continue

            price_change_pct = abs(float(tk.get("priceChangePercent", 0)))
            if price_change_pct < MIN_PRICE_CHANGE_PCT:
                continue
            if price_change_pct > MAX_PRICE_CHANGE_PCT:
                continue

            trade_count = int(tk.get("count", 0))
            if trade_count < MIN_TRADE_COUNT_24H:
                continue

            # --- spread from bookTicker ---
            bt = book_map.get(symbol, {})
            bid = float(bt.get("bidPrice", 0))
            ask = float(bt.get("askPrice", 0))
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid
            if spread_pct > MAX_SPREAD_PCT:
                continue

            # --- composite score (higher = better for scalping) ---
            # Normalize each component to 0-1 range then weight
            vol_score = min(quote_volume / 1_000_000_000.0, 1.0)  # cap at $1B (was $500M — SOL/DOGE reach $2-5B)
            spread_score = 1.0 - (spread_pct / MAX_SPREAD_PCT)  # tighter = better
            vol_score_change = min(price_change_pct / 15.0, 1.0)  # cap at 15%
            trade_score = min(trade_count / 1_000_000, 1.0)  # cap at 1M trades

            composite = (
                vol_score * 0.25           # volume weight
                + spread_score * 0.20      # spread weight
                + vol_score_change * 0.20  # volatility weight
                + trade_score * 0.15       # activity weight
                # depth_score added after fetch below
            )

            candidates.append(CoinScore(
                symbol=symbol,
                quote_volume=quote_volume,
                spread_pct=spread_pct,
                price_change_pct=price_change_pct,
                trade_count=trade_count,
                depth_score=0.0,
                composite_score=composite,
            ))

        # Fetch depth for top candidates and add depth_score (0.20 weight)
        # Limit to top 25 by pre-score to avoid excessive API calls
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        depth_candidates = candidates[:25]
        if self._client and depth_candidates:
            depth_tasks = [
                self._client.get_depth(c.symbol, limit=20)
                for c in depth_candidates
            ]
            depths = await asyncio.gather(*depth_tasks, return_exceptions=True)
            for c, d in zip(depth_candidates, depths):
                if isinstance(d, dict):
                    c.depth_score = _depth_imbalance_score(d)
                c.composite_score += c.depth_score * 0.20

        # Sort by composite score descending, pick top N
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        top = candidates[:MAX_SYMBOLS]

        if top:
            logger.info(
                f"CoinScreener: {len(candidates)} passed filters, "
                f"selected top {len(top)}:",
            )
            for i, c in enumerate(top):
                logger.info(
                    f"  #{i+1} {c.symbol} "
                    f"vol=${c.quote_volume/1e6:.0f}M "
                    f"spread={c.spread_pct*100:.4f}% "
                    f"change={c.price_change_pct:.1f}% "
                    f"trades={c.trade_count/1000:.0f}k "
                    f"depth={c.depth_score:.2f} "
                    f"score={c.composite_score:.3f}",
                )
        else:
            logger.warning("CoinScreener: no coins passed filters!")

        return [c.symbol for c in top]
