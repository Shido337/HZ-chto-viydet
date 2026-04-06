from __future__ import annotations

import pytest

from core.coin_screener import (
    CoinScreener,
    EXCLUDED_SYMBOLS,
    MAX_SPREAD_PCT,
    MAX_SYMBOLS,
    MIN_PRICE_CHANGE_PCT,
    MIN_QUOTE_VOLUME_24H,
    MIN_TRADE_COUNT_24H,
)


def _make_ticker(
    symbol: str,
    quote_volume: float = 100_000_000.0,
    price_change_pct: float = 5.0,
    trade_count: int = 500_000,
) -> dict:
    return {
        "symbol": symbol,
        "quoteVolume": str(quote_volume),
        "priceChangePercent": str(price_change_pct),
        "count": str(trade_count),
    }


def _make_book(symbol: str, bid: float = 1.0, ask: float = 1.0002) -> dict:
    return {
        "symbol": symbol,
        "bidPrice": str(bid),
        "askPrice": str(ask),
    }


class TestCoinScreener:

    def setup_method(self) -> None:
        self.screener = CoinScreener()

    def test_basic_screening_returns_symbols(self) -> None:
        tickers = [_make_ticker("TOKENUSDT")]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == ["TOKENUSDT"]

    def test_excludes_non_usdt(self) -> None:
        tickers = [_make_ticker("TOKENBUSD")]
        books = [_make_book("TOKENBUSD")]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_excludes_large_cap(self) -> None:
        # SOLUSDT is intentionally allowed (high volume, tight spread, real structure)
        for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
            tickers = [_make_ticker(sym)]
            books = [_make_book(sym)]
            result = self.screener.screen(tickers, books)
            assert sym not in result

    def test_filters_low_volume(self) -> None:
        tickers = [_make_ticker("TOKENUSDT", quote_volume=1_000_000)]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_filters_low_volatility(self) -> None:
        tickers = [_make_ticker("TOKENUSDT", price_change_pct=0.3)]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_filters_extreme_volatility(self) -> None:
        tickers = [_make_ticker("TOKENUSDT", price_change_pct=50.0)]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_filters_low_trade_count(self) -> None:
        tickers = [_make_ticker("TOKENUSDT", trade_count=10_000)]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_filters_wide_spread(self) -> None:
        # spread = (1.01 - 1.0) / 1.005 ≈ 0.995% >> 0.05%
        tickers = [_make_ticker("TOKENUSDT")]
        books = [_make_book("TOKENUSDT", bid=1.0, ask=1.01)]
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_ranks_by_composite_score(self) -> None:
        tickers = [
            _make_ticker("LOWUSDT", quote_volume=110_000_000, price_change_pct=2.0),
            _make_ticker("HIGHUSDT", quote_volume=300_000_000, price_change_pct=10.0,
                         trade_count=800_000),
        ]
        books = [
            _make_book("LOWUSDT"),
            _make_book("HIGHUSDT"),
        ]
        result = self.screener.screen(tickers, books)
        assert result[0] == "HIGHUSDT"
        assert result[1] == "LOWUSDT"

    def test_limits_to_max_symbols(self) -> None:
        tickers = [
            _make_ticker(f"TOKEN{i}USDT", quote_volume=100_000_000 + i * 1_000_000)
            for i in range(20)
        ]
        books = [
            _make_book(f"TOKEN{i}USDT")
            for i in range(20)
        ]
        result = self.screener.screen(tickers, books)
        assert len(result) <= MAX_SYMBOLS

    def test_perpetual_filter(self) -> None:
        self.screener.set_perpetual_symbols([
            {"symbol": "AAAUSDT"},
            {"symbol": "BBBUSDT"},
        ])
        tickers = [
            _make_ticker("AAAUSDT"),
            _make_ticker("BBBUSDT"),
            _make_ticker("CCCUSDT"),  # not in perpetual list
        ]
        books = [
            _make_book("AAAUSDT"),
            _make_book("BBBUSDT"),
            _make_book("CCCUSDT"),
        ]
        result = self.screener.screen(tickers, books)
        assert "AAAUSDT" in result
        assert "BBBUSDT" in result
        assert "CCCUSDT" not in result

    def test_empty_input_returns_empty(self) -> None:
        result = self.screener.screen([], [])
        assert result == []

    def test_missing_book_ticker_skips(self) -> None:
        tickers = [_make_ticker("TOKENUSDT")]
        books = []  # no book data
        result = self.screener.screen(tickers, books)
        assert result == []

    def test_negative_price_change_uses_abs(self) -> None:
        tickers = [_make_ticker("TOKENUSDT", price_change_pct=-5.0)]
        books = [_make_book("TOKENUSDT")]
        result = self.screener.screen(tickers, books)
        assert result == ["TOKENUSDT"]

    def test_tight_spread_scores_higher(self) -> None:
        tickers = [
            _make_ticker("TIGHTUSDT"),
            _make_ticker("WIDEUSDT"),
        ]
        books = [
            _make_book("TIGHTUSDT", bid=1.0, ask=1.00001),  # very tight
            _make_book("WIDEUSDT", bid=1.0, ask=1.0004),    # wider but still ok
        ]
        result = self.screener.screen(tickers, books)
        assert result[0] == "TIGHTUSDT"
