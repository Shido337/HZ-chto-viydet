from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from dotenv import load_dotenv
from loguru import logger

from core.paper_trader import PaperTrader
from core.regime_classifier import RegimeClassifier
from core.risk_manager import RiskManager
from core.signal_generator import PendingOrder, Signal
from core.coin_screener import CoinScreener, SCREENER_INTERVAL
from data.cache import AdaptiveParams, MarketCache, MarketRegime
from exchange.binance_client import BinanceClient
from exchange.binance_ws import BinanceWS
from exchange.order_executor import OrderExecutor
from ml.online_learner import OnlineLearner
from strategies.continuation_break import ContinuationBreak
from strategies.early_momentum import EarlyMomentum
from strategies.mean_reversion import MeanReversion

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REGIME_UPDATE_INTERVAL = 30  # seconds
LOOP_INTERVAL = 1.0
MAX_CONSECUTIVE_ERRORS = 10
MAX_SIGNALS_HISTORY = 200


class BotEngine:
    """Main orchestrator — ties all modules together."""

    def __init__(self) -> None:
        self.cache = MarketCache()
        self.client = BinanceClient()
        self.executor = OrderExecutor(self.client)
        self.risk = RiskManager()
        self.classifier = RegimeClassifier()
        self.learner = OnlineLearner()

        self.strategies = [
            ContinuationBreak(),
            MeanReversion(),
            EarlyMomentum(),
        ]
        self.strategy_enabled = {
            "CONTINUATION_BREAK": True,
            "MEAN_REVERSION": True,
            "EARLY_MOMENTUM": True,
        }

        # Trader — paper by default, swappable
        self.trader: PaperTrader = PaperTrader(self.cache)
        self.mode = "paper"

        # Dynamic coin screening (replaces hardcoded symbols)
        self.screener = CoinScreener()
        self.symbols: list[str] = []
        # Fallback if screening fails
        self._fallback_symbols: list[str] = [
            "1000PEPEUSDT", "1000FLOKIUSDT", "WIFUSDT", "1000BONKUSDT",
            "ORDIUSDT", "1000SHIBUSDT", "FETUSDT", "APEUSDT",
            "GALAUSDT", "TURBOUSDT", "MEMEUSDT", "PEOPLEUSDT",
        ]
        self._ws: BinanceWS | None = None
        self._running = False
        self._main_task: asyncio.Task[None] | None = None
        self._consecutive_errors = 0
        self._last_regime_update = 0.0
        self._last_status_log = 0.0
        self._tick_count = 0
        self._on_trade_close: Any = None  # callback for server WS
        self._on_signal: Any = None
        self._on_regime: Any = None
        self._on_position_opened: Any = None
        self._on_kline_update: Any = None
        self._on_pending_placed: Any = None
        self._on_pending_cancelled: Any = None
        self.signals: list[Signal] = []
        self._signal_cooldown: dict[str, float] = {}  # symbol → last signal time
        self._last_screen_time = 0.0
        self._testnet = False

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        await self.client.start()
        # Pre-load exchange filters (LOT_SIZE, PRICE_FILTER) for order precision
        await self.executor.load_filters()
        balance = await self.client.get_balance()
        self.risk.session_start_balance = balance if balance > 0 else 10000.0
        logger.info(f"Starting balance: ${self.risk.session_start_balance:.2f}")

        # Dynamic coin screening
        await self._run_screening()
        if not self.symbols:
            logger.warning("Screening returned 0 coins, using fallback list")
            self.symbols = list(self._fallback_symbols)

        self._init_symbols()
        await self._load_historical_klines()
        await self._update_regimes()
        await self._start_ws(self._testnet)
        self._running = True
        self._main_task = asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        self._running = False
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.stop()
        await self.client.close()

    def switch_mode(self, mode: str) -> None:
        """Swap between paper and live trader."""
        if mode == self.mode:
            return
        if mode == "live":
            from core.live_trader import LiveTrader
            self.trader = LiveTrader(self.cache, self.client, self.executor)
        else:
            self.trader = PaperTrader(self.cache)
        self.mode = mode
        logger.info(f"Trader switched to {mode}")

    async def recover_live_positions(self) -> None:
        """Recover open positions from exchange (call after switch to live)."""
        if self.mode != "live" or not hasattr(self.trader, "recover_positions"):
            return
        await self.trader.recover_positions()
        logger.info(f"Recovered {self.trader.open_count} live positions")

    # -- main loop ----------------------------------------------------------

    async def _main_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
                self._consecutive_errors = 0
            except asyncio.CancelledError:
                return
            except Exception:
                self._consecutive_errors += 1
                logger.exception(
                    f"Main loop error ({self._consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})",
                )
                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("Too many consecutive errors, pausing 60s")
                    await asyncio.sleep(60)
                    self._consecutive_errors = 0
            await asyncio.sleep(LOOP_INTERVAL)

    async def _tick(self) -> None:
        now = time.time()
        self._tick_count += 1

        if now - self._last_regime_update >= REGIME_UPDATE_INTERVAL:
            await self._update_regimes()
            self._last_regime_update = now

        # Periodic coin re-screening
        if now - self._last_screen_time >= SCREENER_INTERVAL:
            await self._rotate_symbols()

        # Periodic status log (every 60s)
        if now - self._last_status_log >= 60:
            self._last_status_log = now
            for symbol in self.symbols:
                snap = self.cache.get_snapshot(symbol)
                regime = self.cache.regime.get(symbol, "?")
                klen = len(self.cache.klines.get(symbol, {}).get("5m", []))
                logger.info(
                    f"[STATUS] {symbol} price={snap.price:.6f} "
                    f"regime={regime} 5m_candles={klen} "
                    f"cvd_delta={snap.cvd_delta_1m:.0f} "
                    f"adx={snap.indicators.adx:.1f} "
                    f"positions={self.trader.open_count} "
                    f"signals={len(self.signals)} "
                    f"ticks={self._tick_count}",
                )
            self._diagnose_strategies()

        # Check pending limit orders (PaperTrader only)
        if hasattr(self.trader, "check_pending"):
            filled, expired = self.trader.check_pending()
            for pos in filled:
                if self._on_pending_cancelled:
                    await self._on_pending_cancelled(pos)
                if self._on_position_opened:
                    await self._on_position_opened(pos)
            for order in expired:
                if self._on_pending_cancelled:
                    await self._on_pending_cancelled(order)

        # Update existing positions (sync for PaperTrader, async for LiveTrader)
        result = self.trader.update_positions()
        if asyncio.iscoroutine(result):
            closed = await result
        else:
            closed = result

        for pos, reason in closed:
            won = pos.current_pnl > 0
            self.risk.daily_pnl += pos.current_pnl
            self.learner.record(pos.setup_type.value, pos.symbol, won)
            await self._persist_trade(pos, reason)
            if self._on_trade_close:
                await self._on_trade_close(pos, reason)

        if self.risk.check_daily_limit():
            return

        # Generate new signals
        for symbol in self.symbols:
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            if symbol in self.trader.positions:
                continue
            # Skip symbols with pending limit orders
            if hasattr(self.trader, "pending") and symbol in self.trader.pending:
                continue
            # Signal cooldown: 60s per symbol to prevent spam
            if now - self._signal_cooldown.get(symbol, 0) < 60:
                continue
            signal = self._find_signal(snap)
            if signal:
                self._signal_cooldown[symbol] = now
                self.signals.append(signal)
                if len(self.signals) > MAX_SIGNALS_HISTORY:
                    self.signals = self.signals[-MAX_SIGNALS_HISTORY:]
                if self._on_signal:
                    await self._on_signal(signal)
                await self._process_signal(signal)

    # -- signal search ------------------------------------------------------

    def _find_signal(self, snap: Any) -> Signal | None:
        for strategy in self.strategies:
            name = strategy.__class__.__name__
            setup = self._class_to_setup(name)
            if not self.strategy_enabled.get(setup, True):
                continue
            # LOW_VOL → MR or EM only (CB needs trending)
            if snap.regime == MarketRegime.LOW_VOL:
                if setup not in ("EARLY_MOMENTUM", "MEAN_REVERSION"):
                    continue
            boost = self.learner.predict_boost(setup, snap.symbol)
            sig = strategy.compute_signal(snap, boost)
            if sig:
                logger.info(
                    f"SIGNAL {sig.symbol} {sig.direction.value} "
                    f"{sig.setup_type.value} score={sig.score:.3f}",
                )
                return sig
        return None

    # -- diagnostics --------------------------------------------------------

    def _diagnose_strategies(self) -> None:
        """Log why each strategy rejects each symbol (runs every status cycle)."""
        from data.indicators import (
            atr_percentile as calc_atr_pct,
            detect_swing_high,
            detect_swing_low,
            order_book_imbalance,
            volume_spike_ratio,
        )

        for symbol in self.symbols:
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            if symbol in self.trader.positions:
                continue
            regime = snap.regime
            adx_val = snap.indicators.adx
            ob = order_book_imbalance(snap.bid_qty, snap.ask_qty)

            # ContinuationBreak diagnosis (TRENDING)
            if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
                candles_3m = list(snap.klines_3m)
                reason = "CB: "
                if len(candles_3m) < 12:
                    reason += "need 12+ 3m candles"
                else:
                    last = candles_3m[-1]
                    body_pct = abs(last["c"] - last["o"]) / last["o"] if last["o"] else 0
                    swing_h = detect_swing_high(candles_3m[:-1], 5)
                    swing_l = detect_swing_low(candles_3m[:-1], 5)
                    broke_h = last["c"] > swing_h and last["c"] > last["o"]
                    broke_l = last["c"] < swing_l and last["c"] < last["o"]
                    candles_1m = list(snap.klines_1m)
                    vol_ratio = volume_spike_ratio(candles_1m) if len(candles_1m) > 2 else 0
                    if body_pct < 0.0002:
                        reason += f"body={body_pct:.4f}<0.0002"
                    elif not broke_h and not broke_l:
                        reason += f"no brk (c={last['c']:.6f} H={swing_h:.6f} L={swing_l:.6f})"
                    elif snap.cvd_delta_1m == 0:
                        reason += "cvd=0"
                    elif ob < 0.55 and (1 - ob) < 0.55:
                        reason += f"ob={ob:.2f}<0.55"
                    else:
                        if len(candles_1m) >= 3:
                            recent = candles_1m[-2:]
                            greens = sum(1 for c in recent if c["c"] > c["o"])
                            reds = sum(1 for c in recent if c["c"] < c["o"])
                            reason += f"mom g={greens} r={reds} vol={vol_ratio:.2f}"
                        else:
                            reason += "need 3+ 1m candles"
                logger.info(f"[DIAG] {symbol} {reason}")

            # EarlyMomentum diagnosis (ADX 18-30)
            if 18.0 <= adx_val <= 30.0:
                candles_5m = list(snap.klines_5m)
                reason = "EM: "
                if len(candles_5m) < 16:
                    reason += "need 16+ 5m candles"
                else:
                    atr_pct = calc_atr_pct(candles_5m, 14, 576)
                    candles_1m = list(snap.klines_1m)
                    if atr_pct >= 55.0:
                        reason += f"atr_pct={atr_pct:.1f}>=55"
                    elif len(candles_1m) < 3:
                        reason += "need 3+ 1m candles"
                    else:
                        recent = candles_1m[-1:]
                        all_up = all(c["c"] > c["o"] for c in recent)
                        all_dn = all(c["c"] < c["o"] for c in recent)
                        if not all_up and not all_dn:
                            reason += f"dir=flat cvd={snap.cvd_delta_1m:.0f}"
                        elif (all_up and snap.cvd_delta_1m <= 0) or (all_dn and snap.cvd_delta_1m >= 0):
                            reason += f"cvd mismatch up={all_up} cvd={snap.cvd_delta_1m:.0f}"
                        else:
                            d = "LONG" if all_up else "SHORT"
                            # Check OB & level proximity
                            level = detect_swing_high(candles_5m, 10) if all_up else detect_swing_low(candles_5m, 10)
                            prox = abs(snap.price - level) / level if level else 999
                            reason += f"{d} ob={ob:.2f} lvl={level:.6f} prox={prox*100:.2f}%"
                logger.info(f"[DIAG] {symbol} {reason}")

            # MeanReversion diagnosis (RANGING / LOW_VOL / HIGH_VOL)
            if regime in (
                MarketRegime.RANGING, MarketRegime.LOW_VOL, MarketRegime.HIGH_VOL,
            ):
                candles_1m = list(snap.klines_1m)
                reason = "MR: "
                if len(candles_1m) < 8:
                    reason += f"need 8+ 1m candles (have {len(candles_1m)})"
                else:
                    sw_h = detect_swing_high(candles_1m[:-1], 5)
                    sw_l = detect_swing_low(candles_1m[:-1], 5)
                    swept_h = any(
                        c["h"] > sw_h and c["c"] < sw_h
                        for c in candles_1m[-3:]
                    )
                    swept_l = any(
                        c["l"] < sw_l and c["c"] > sw_l
                        for c in candles_1m[-3:]
                    )
                    reason += (
                        f"swept_h={swept_h} swept_l={swept_l} "
                        f"cvd={snap.cvd_delta_1m:.0f} ob={ob:.2f}"
                    )
                logger.info(f"[DIAG] {symbol} {reason}")

    # -- signal processing --------------------------------------------------

    async def _process_signal(self, signal: Signal) -> None:
        snap = self.cache.get_snapshot(signal.symbol)

        size = self.risk.compute_size(
            balance=self.risk.session_start_balance + self.risk.daily_pnl,
            score=signal.score,
            regime=snap.regime,
            open_count=self.trader.open_count,
            sl_pct=abs(signal.entry_price - signal.sl_price)
            / signal.entry_price
            if signal.entry_price
            else 0.0,
        )
        if size <= 0:
            return
        result = self.trader.open_position(signal, size)
        if asyncio.iscoroutine(result):
            result = await result
        if result is None:
            return
        # PaperTrader returns PendingOrder, LiveTrader returns Position
        if isinstance(result, PendingOrder):
            if self._on_pending_placed:
                await self._on_pending_placed(result)
        else:
            if self._on_position_opened:
                await self._on_position_opened(result)

    # -- historical data preload ---------------------------------------------

    async def _load_historical_klines(self) -> None:
        """Fetch candles from REST so strategies have data immediately."""
        timeframes = [("1m", 500), ("3m", 500), ("5m", 500)]
        for symbol in self.symbols:
            for tf, limit in timeframes:
                try:
                    candles = await self.client.get_klines(symbol, tf, limit)
                    if candles:
                        self.cache.load_klines(symbol, tf, candles)
                        logger.info(
                            f"Loaded {len(candles)} {tf} candles for {symbol}",
                        )
                except Exception:
                    logger.warning(f"Failed to load {tf} klines for {symbol}")

    # -- trade persistence --------------------------------------------------

    async def _persist_trade(
        self, pos: Any, reason: str,
    ) -> None:
        """Save closed trade to DB."""
        try:
            from datetime import datetime, timezone

            from data.database import async_session_factory
            from data.models import Trade, TradeDirection, TradeResult
            from data.models import SetupType as DBSetupType

            result = TradeResult.WIN if pos.current_pnl > 0 else TradeResult.LOSS
            if abs(pos.current_pnl) < 0.01:
                result = TradeResult.BREAKEVEN

            async with async_session_factory() as session:
                trade = Trade(
                    symbol=pos.symbol,
                    direction=TradeDirection(pos.direction.value),
                    setup_type=DBSetupType(pos.setup_type.value),
                    score=pos.score,
                    entry_price=pos.entry_price,
                    exit_price=self.cache.get_snapshot(pos.symbol).price,
                    sl_price=pos.sl_price,
                    tp_price=pos.tp_price,
                    size_usdt=pos.size_usdt,
                    pnl=pos.current_pnl,
                    result=result,
                    exit_reason=reason,
                    opened_at=datetime.fromtimestamp(
                        pos.opened_at, tz=timezone.utc,
                    ),
                    closed_at=datetime.now(timezone.utc),
                )
                session.add(trade)
                await session.commit()
        except Exception:
            logger.exception("Failed to persist trade")

    # -- regime update ------------------------------------------------------

    async def _update_regimes(self) -> None:
        for symbol in self.symbols:
            candles_5m = list(self.cache.klines.get(symbol, {}).get("5m", []))
            if len(candles_5m) < 16:
                continue
            regime, indicators = self.classifier.classify(candles_5m)
            await self.cache.update_regime(symbol, regime)
            await self.cache.update_indicators(symbol, indicators)
            if self._on_regime:
                await self._on_regime(symbol, regime.value)
            # Compute ATR-adaptive params per symbol
            await self._compute_adaptive_params(symbol, regime, indicators.atr, indicators.atr_percentile)

    # -- adaptive params computation ----------------------------------------

    async def _compute_adaptive_params(
        self,
        symbol: str,
        regime: MarketRegime,
        atr_val: float,
        atr_pct: float,
    ) -> None:
        """Compute AdaptiveParams per symbol from regime, ATR, and learner feedback."""
        if atr_val <= 0:
            return

        # --- SL bounds (ATR-multiples) adjusted by regime ---
        # Base: 0.5–2.0 ATR.  Tighter in trending (clear structure),
        # wider in ranging/high-vol (noise).
        if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            max_sl = 2.0
            min_sl = 0.4
        elif regime == MarketRegime.HIGH_VOL:
            max_sl = 3.0
            min_sl = 0.8
        elif regime == MarketRegime.LOW_VOL:
            max_sl = 2.5
            min_sl = 0.3
        else:  # RANGING
            max_sl = 2.5
            min_sl = 0.5

        # --- TP ratio adjusted by regime ---
        if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            tp_rr = 2.0   # trends run further — let trailing catch more
        elif regime == MarketRegime.HIGH_VOL:
            tp_rr = 1.5   # take profits, but not too soon
        elif regime == MarketRegime.LOW_VOL:
            tp_rr = 2.0   # low vol = need wider target
        else:  # RANGING
            tp_rr = 1.5

        # --- Trailing distances (ATR-relative) ---
        if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            trail_activation = 0.3   # activate early in trends
            trail_distance = 0.2     # tight trail to lock profits fast
            be_trigger = 0.25
        elif regime == MarketRegime.HIGH_VOL:
            trail_activation = 0.6   # moderate in high vol
            trail_distance = 0.4     # wider trail for noise
            be_trigger = 0.5
        else:  # RANGING / LOW_VOL
            trail_activation = 0.4
            trail_distance = 0.25
            be_trigger = 0.35

        # --- OB & volume thresholds adjusted by ATR percentile ---
        # Low ATR percentile = quiet market → relax filters to find trades
        # High ATR percentile = active market → tighten for quality
        if atr_pct < 30:
            ob_min = 0.52
            vol_spike_min = 0.5
        elif atr_pct < 60:
            ob_min = 0.55
            vol_spike_min = 0.7
        else:
            ob_min = 0.58
            vol_spike_min = 0.9

        # --- Learner feedback into min_score ---
        base_score = 0.65
        # Check all setup types and take the most relevant adjustment
        adjustments: list[float] = []
        for setup_name in ("CONTINUATION_BREAK", "MEAN_REVERSION", "EARLY_MOMENTUM"):
            adj = self.learner.get_score_adjustment(setup_name, symbol)
            if adj != 0.0:
                adjustments.append(adj)
        # Use average adjustment if any, otherwise 0
        score_delta = sum(adjustments) / len(adjustments) if adjustments else 0.0
        min_score = max(0.50, min(0.80, base_score + score_delta))

        params = AdaptiveParams(
            max_sl_atr=max_sl,
            min_sl_atr=min_sl,
            tp_rr=tp_rr,
            trail_activation_atr=trail_activation,
            trail_distance_atr=trail_distance,
            breakeven_trigger_atr=be_trigger,
            min_score=min_score,
            volume_spike_min=vol_spike_min,
            ob_min=ob_min,
            atr_value=atr_val,
        )
        await self.cache.update_adaptive(symbol, params)

    # -- WebSocket setup ----------------------------------------------------

    def _init_symbols(self) -> None:
        for s in self.symbols:
            self.cache.init_symbol(s)

    async def _start_ws(self, testnet: bool) -> None:
        self._ws = BinanceWS(testnet=testnet)
        for s in self.symbols:
            sl = s.lower()
            self._ws.subscribe(f"{sl}@kline_1m", self._make_kline_handler(s, "1m"))
            self._ws.subscribe(f"{sl}@kline_3m", self._make_kline_handler(s, "3m"))
            self._ws.subscribe(f"{sl}@kline_5m", self._make_kline_handler(s, "5m"))
            self._ws.subscribe(f"{sl}@bookTicker", self._make_book_handler(s))
            self._ws.subscribe(f"{sl}@aggTrade", self._make_agg_handler(s))
        await self._ws.start()

    # -- dynamic coin screening ---------------------------------------------

    async def _run_screening(self) -> None:
        """Fetch tickers from Binance and screen for best scalping coins."""
        try:
            # Load perpetual symbols list (once)
            if not self.screener._perpetual_symbols:
                perp_info = await self.client.get_exchange_info_symbols()
                self.screener.set_perpetual_symbols(perp_info)

            tickers = await self.client.get_all_tickers_24hr()
            book_tickers = await self.client.get_all_book_tickers()
            selected = self.screener.screen(tickers, book_tickers)
            if selected:
                self.symbols = selected
            self._last_screen_time = time.time()
        except Exception:
            logger.exception("Coin screening failed")
            if not self.symbols:
                self.symbols = list(self._fallback_symbols)

    async def _rotate_symbols(self) -> None:
        """Re-screen coins and reconnect WS if symbol set changed."""
        old_symbols = set(self.symbols)
        await self._run_screening()
        new_symbols = set(self.symbols)

        if old_symbols == new_symbols:
            return

        added = new_symbols - old_symbols
        removed = old_symbols - new_symbols

        # Don't remove symbols with open positions
        open_syms = set(self.trader.positions.keys())
        kept_from_removed = removed & open_syms
        if kept_from_removed:
            logger.info(f"Keeping {kept_from_removed} (open positions)")
            removed -= kept_from_removed
            self.symbols = list(new_symbols | kept_from_removed)

        if not added and not removed:
            return

        logger.info(
            f"Symbol rotation: +{len(added)} -{len(removed)} "
            f"(added={added}, removed={removed})",
        )

        # Init cache for new symbols
        for s in added:
            self.cache.init_symbol(s)

        # Load historical klines for new symbols
        for s in added:
            for tf, limit in [("1m", 500), ("3m", 500), ("5m", 500)]:
                try:
                    candles = await self.client.get_klines(s, tf, limit)
                    if candles:
                        self.cache.load_klines(s, tf, candles)
                except Exception:
                    logger.warning(f"Failed to load {tf} klines for {s}")

        # Reconnect WS with new symbol set
        if self._ws:
            await self._ws.stop()
        await self._start_ws(self._testnet)

    # -- WS handlers --------------------------------------------------------

    def _make_kline_handler(self, symbol: str, tf: str) -> Any:
        async def handler(data: dict[str, Any]) -> None:
            k = data.get("k", {})
            candle = {
                "t": k.get("t", 0),
                "o": float(k.get("o", 0)),
                "h": float(k.get("h", 0)),
                "l": float(k.get("l", 0)),
                "c": float(k.get("c", 0)),
                "v": float(k.get("v", 0)),
                "T": k.get("T", 0),
                "closed": k.get("x", False),
            }
            await self.cache.update_kline(symbol, tf, candle)
            # Rotate CVD delta on 1m close
            if tf == "1m" and candle["closed"]:
                self.cache.rotate_1m_delta(symbol)
            # Forward every candle tick to dashboard (live updates)
            if self._on_kline_update:
                await self._on_kline_update(symbol, tf, candle)
        return handler

    def _make_book_handler(self, symbol: str) -> Any:
        async def handler(data: dict[str, Any]) -> None:
            await self.cache.update_book(
                symbol,
                bid=float(data.get("b", 0)),
                ask=float(data.get("a", 0)),
                bid_qty=float(data.get("B", 0)),
                ask_qty=float(data.get("A", 0)),
            )
        return handler

    def _make_agg_handler(self, symbol: str) -> Any:
        async def handler(data: dict[str, Any]) -> None:
            await self.cache.update_agg_trade(symbol, data)
        return handler

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _class_to_setup(cls_name: str) -> str:
        mapping = {
            "ContinuationBreak": "CONTINUATION_BREAK",
            "MeanReversion": "MEAN_REVERSION",
            "EarlyMomentum": "EARLY_MOMENTUM",
        }
        return mapping.get(cls_name, cls_name)
