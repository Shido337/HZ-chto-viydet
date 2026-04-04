from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Screening thresholds
# ---------------------------------------------------------------------------
MIN_QUOTE_VOLUME_24H = 50_000_000.0    # $50M min 24h USDT volume
MAX_SPREAD_PCT = 0.0005                  # 0.05% max bid-ask spread
MIN_PRICE_CHANGE_PCT = 1.0              # min 1% daily move (abs)
MAX_PRICE_CHANGE_PCT = 30.0             # max 30% daily move (abs)
MIN_TRADE_COUNT_24H = 100_000           # min 100k trades in 24h
MAX_SYMBOLS = 12                        # top N to select
SCREENER_INTERVAL = 300                 # re-screen every 5 minutes

# Coins to always exclude (stablecoins, illiquid wrappers)
EXCLUDED_SYMBOLS: set[str] = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
}
# Note: we exclude top-cap coins because they move too slowly for
# micro-scalping on $50 positions. We want volatile altcoins.


@dataclass
class CoinScore:
    """Screening metrics for one symbol."""
    symbol: str
    quote_volume: float       # USDT 24h volume
    spread_pct: float         # bid-ask spread %
    price_change_pct: float   # abs 24h price change %
    trade_count: int          # 24h trade count
    composite_score: float    # final ranking score


class CoinScreener:
    """Dynamic coin selection based on volume, spread, and volatility."""

    def __init__(self) -> None:
        self._perpetual_symbols: set[str] = set()

    def set_perpetual_symbols(self, symbols: list[dict[str, Any]]) -> None:
        """Cache valid PERPETUAL USDT-M symbol names from exchangeInfo."""
        self._perpetual_symbols = {s.get("symbol", "") for s in symbols}
        logger.info(f"CoinScreener: {len(self._perpetual_symbols)} perpetual pairs loaded")

    def screen(
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
            vol_score = min(quote_volume / 500_000_000.0, 1.0)  # cap at $500M
            spread_score = 1.0 - (spread_pct / MAX_SPREAD_PCT)  # tighter = better
            vol_score_change = min(price_change_pct / 15.0, 1.0)  # cap at 15%
            trade_score = min(trade_count / 1_000_000, 1.0)  # cap at 1M trades

            composite = (
                vol_score * 0.30           # volume weight
                + spread_score * 0.25      # spread weight
                + vol_score_change * 0.25  # volatility weight
                + trade_score * 0.20       # activity weight
            )

            candidates.append(CoinScore(
                symbol=symbol,
                quote_volume=quote_volume,
                spread_pct=spread_pct,
                price_change_pct=price_change_pct,
                trade_count=trade_count,
                composite_score=composite,
            ))

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
                    f"score={c.composite_score:.3f}",
                )
        else:
            logger.warning("CoinScreener: no coins passed filters!")

        return [c.symbol for c in top]
