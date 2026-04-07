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
from data.cache import AdaptiveParams, LocalOrderBook, MarketCache, MarketRegime
from exchange.binance_client import BinanceClient
from exchange.binance_ws import BinanceWS
from exchange.order_executor import OrderExecutor
from ml.online_learner import OnlineLearner
from strategies.continuation_break import ContinuationBreak
from strategies.early_momentum import EarlyMomentum
from strategies.mean_reversion import MeanReversion
from strategies.wall_bounce import WallBounce

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
            WallBounce(),
        ]
        self.strategy_enabled = {
            "CONTINUATION_BREAK": True,   # re-enabled: SL cap 0.8%, ADX≤40, rejection candle filter
            "MEAN_REVERSION": True,
            "EARLY_MOMENTUM": True,
            "WALL_BOUNCE": True,
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
        self._user_ws: BinanceWS | None = None  # user data stream for order events
        self._listen_key: str = ""
        self._listen_key_task: asyncio.Task[None] | None = None
        self._order_books: dict[str, LocalOrderBook] = {}  # full incremental order books
        self._running = False
        self._main_task: asyncio.Task[None] | None = None
        self._consecutive_errors = 0
        self._last_regime_update = 0.0
        self._last_status_log = 0.0
        self._tick_count = 0
        self._on_trade_close: Any = None  # callback for server WS
        self._on_signal: Any = None
        self._on_signal_expired: Any = None
        self._on_regime: Any = None
        self._on_position_opened: Any = None
        self._on_kline_update: Any = None
        self._on_pending_placed: Any = None
        self._on_pending_cancelled: Any = None
        self.signals: list[Signal] = []
        self._signal_cooldown: dict[str, float] = {}  # symbol → last signal time
        self._last_screen_time = 0.0
        self._testnet = False
        self.started_at: str = ""

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        await self.client.start()
        # Pre-load exchange filters (LOT_SIZE, PRICE_FILTER) for order precision
        await self.executor.load_filters()
        from datetime import datetime, timezone
        # ISO format matching API's .isoformat() for correct date comparison
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
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
        if self._listen_key_task and not self._listen_key_task.done():
            self._listen_key_task.cancel()
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        if self._user_ws:
            await self._user_ws.stop()
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
        """Recover open positions from exchange (call after switch to live).

        Also starts user data stream for order event notifications.
        """
        if self.mode != "live" or not hasattr(self.trader, "recover_positions"):
            return
        await self.trader.recover_positions()
        await self._start_user_data_stream()
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
                # Reset cooldown: expired order frees the symbol for other setups
                self._signal_cooldown.pop(order.symbol, None)

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
            # Reset cooldown so another strategy can immediately re-enter
            self._signal_cooldown.pop(pos.symbol, None)

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
            # Signal cooldown: 15s per symbol
            if now - self._signal_cooldown.get(symbol, 0) < 15:
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
        """Run strategies and return the first valid signal (no voting delay)."""
        for strategy in self.strategies:
            name = strategy.__class__.__name__
            setup = self._class_to_setup(name)
            if not self.strategy_enabled.get(setup, True):
                continue
            # LOW_VOL → MR and WB only (no momentum in a dead market; walls are cleaner)
            if snap.regime == MarketRegime.LOW_VOL:
                if setup not in ("MEAN_REVERSION", "WALL_BOUNCE"):
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

            # ContinuationBreak diagnosis (TRENDING) — mirrors _detect_break_and_retest
            if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
                from strategies.continuation_break import (
                    SWING_LOOKBACK as _CB_SWING,
                    BREAK_LOOKBACK as _CB_BREAK,
                    BODY_MIN_PCT as _CB_BODY,
                    BREAK_CLEARANCE_PCT as _CB_CLEAR,
                    RETEST_PROXIMITY_PCT as _CB_PROX,
                    RETEST_OVERSHOOT_PCT as _CB_OVER,
                )
                candles_3m = list(snap.klines_3m)
                reason = "CB: "
                min_c = _CB_SWING + _CB_BREAK + 1
                if len(candles_3m) < min_c:
                    reason += f"need {min_c}+ 3m candles (have {len(candles_3m)})"
                else:
                    prefix = candles_3m[:-_CB_BREAK]
                    swing_h = detect_swing_high(prefix, _CB_SWING)
                    swing_l = detect_swing_low(prefix, _CB_SWING)
                    brk_dir: str | None = None
                    brk_lvl = 0.0
                    for i in range(len(candles_3m) - _CB_BREAK, len(candles_3m)):
                        c = candles_3m[i]
                        bp = abs(c["c"] - c["o"]) / c["o"] if c["o"] else 0
                        if bp < _CB_BODY:
                            continue
                        if c["c"] > swing_h and c["c"] > c["o"]:
                            if (c["c"] - swing_h) / swing_h < _CB_CLEAR:
                                continue
                            brk_dir, brk_lvl = "LONG", swing_h
                            break
                        if c["c"] < swing_l and c["c"] < c["o"]:
                            if (swing_l - c["c"]) / swing_l < _CB_CLEAR:
                                continue
                            brk_dir, brk_lvl = "SHORT", swing_l
                            break
                    if brk_dir is None:
                        reason += f"no brk (H={swing_h:.5f} L={swing_l:.5f} p={snap.price:.5f})"
                    else:
                        price = snap.price
                        if brk_dir == "LONG":
                            dist = (price - brk_lvl) / brk_lvl
                        else:
                            dist = (brk_lvl - price) / brk_lvl
                        if dist < -_CB_OVER:
                            reason += f"{brk_dir} brk={brk_lvl:.5f} overshoot dist={dist*100:.2f}%"
                        elif dist > _CB_PROX:
                            reason += f"{brk_dir} brk={brk_lvl:.5f} no retest yet dist={dist*100:.2f}%"
                        else:
                            reason += f"{brk_dir} brk={brk_lvl:.5f} RETEST dist={dist*100:.2f}% → cvd={snap.cvd_delta_1m:.0f} ob={ob:.2f}"
                logger.info(f"[DIAG] {symbol} {reason}")

            # EarlyMomentum diagnosis (adaptive ADX window + trending impulse path)
            ap = snap.adaptive
            if ap.em_adx_low <= adx_val <= ap.em_adx_high:
                candles_5m = list(snap.klines_5m)
                reason = "EM: "
                if len(candles_5m) < 16:
                    reason += "need 16+ 5m candles"
                else:
                    atr_pct = calc_atr_pct(candles_5m, 14, 576)
                    candles_1m = list(snap.klines_1m)
                    n_bars = ap.em_cvd_bars
                    if atr_pct >= ap.em_atr_compression_pct:
                        reason += f"atr_pct={atr_pct:.1f}>={ap.em_atr_compression_pct:.0f}"
                    elif len(candles_1m) < n_bars:
                        reason += f"need {n_bars}+ 1m candles"
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
            elif adx_val > ap.em_adx_high and regime in (
                MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR,
            ):
                reason = "EM-TREND: "
                expected_dir = "LONG" if regime == MarketRegime.TRENDING_BULL else "SHORT"
                cvd20 = snap.cvd_delta_20s
                from strategies.early_momentum import TRENDING_CVD_20S_MIN
                cvd_ok = (cvd20 >= TRENDING_CVD_20S_MIN if expected_dir == "LONG"
                          else cvd20 <= -TRENDING_CVD_20S_MIN)
                reason += (
                    f"{expected_dir} cvd20s={cvd20:.0f} "
                    f"ob={ob:.2f} adx={adx_val:.1f} "
                    f"cvd_ok={cvd_ok}"
                )
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
                        for c in candles_1m[-snap.adaptive.mr_sweep_window:]
                    )
                    swept_l = any(
                        c["l"] < sw_l and c["c"] > sw_l
                        for c in candles_1m[-snap.adaptive.mr_sweep_window:]
                    )
                    reason += (
                        f"swept_h={swept_h} swept_l={swept_l} "
                        f"cvd={snap.cvd_delta_1m:.0f} ob={ob:.2f}"
                    )
                logger.info(f"[DIAG] {symbol} {reason}")

            # WallBounce diagnosis (all regimes)
            from data.indicators import find_wall, wall_absorption_pct
            bid_wall = find_wall(snap.depth_bids, mid_price=snap.price)
            ask_wall = find_wall(snap.depth_asks, mid_price=snap.price)
            if bid_wall or ask_wall:
                parts: list[str] = []
                if bid_wall:
                    bwp, bwq = bid_wall
                    dist_b = (snap.price - bwp) / bwp * 100 if bwp else 0.0
                    abs_b = wall_absorption_pct(snap.wall_history, bwp, "bid") * 100
                    parts.append(f"bid={bwp:.4f} qty={bwq:.0f} dist={dist_b:.2f}% abs={abs_b:.0f}%")
                if ask_wall:
                    awp, awq = ask_wall
                    dist_a = (awp - snap.price) / snap.price * 100 if snap.price else 0.0
                    abs_a = wall_absorption_pct(snap.wall_history, awp, "ask") * 100
                    parts.append(f"ask={awp:.4f} qty={awq:.0f} dist={dist_a:.2f}% abs={abs_a:.0f}%")
                logger.info(f"[DIAG] {symbol} WB: {' | '.join(parts)} cvd={snap.cvd_delta_1m:.0f}")
            else:
                logger.info(f"[DIAG] {symbol} WB: depth_bids={len(snap.depth_bids)} asks={len(snap.depth_asks)} (no wall)")

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
        # Signal was consumed — remove it from the dashboard
        if self._on_signal_expired:
            await self._on_signal_expired(signal)
        # PaperTrader returns PendingOrder, LiveTrader returns Position
        if isinstance(result, PendingOrder):
            # Market fills (EM) go straight to positions — notify as opened
            if signal.symbol in self.trader.positions:
                pos = self.trader.positions[signal.symbol]
                if self._on_position_opened:
                    await self._on_position_opened(pos)
            else:
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
                    exit_price=pos.exit_price if pos.exit_price else self.cache.get_snapshot(pos.symbol).price,
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
        base_score = 0.50
        # Check enabled setup types and use the most conservative (tightest) adjustment
        adjustments: list[float] = []
        for setup_name, enabled in self.strategy_enabled.items():
            if not enabled:
                continue
            adj = self.learner.get_score_adjustment(setup_name, symbol)
            if adj != 0.0:
                adjustments.append(adj)
        # Use max (most conservative) — if any strategy is losing, tighten for all
        score_delta = max(adjustments) if adjustments else 0.0
        min_score = max(0.50, min(0.80, base_score + score_delta))

        # --- Entry filters (ATR-percentile driven) ---
        # atr_pct 0 = dead quiet, 100 = extreme volatility
        # Quiet market  → relax entry filters (wider ADX, looser compression)
        # Active market → tighten (narrow ADX, strict compression, more CVD bars)
        #
        # CB: adx_max — CB works IN trending markets, only skip runaway extremes (ADX 80+)
        # Active market (high atr_pct) → allow higher ADX, quiet → lower cap (weak trends)
        cb_adx_max = 55.0 + atr_pct * 0.25             # range ~55–80
        # EM: ADX window widens in quiet markets, narrows in active
        em_adx_low = 12.0 + atr_pct * 0.08              # range ~12–20
        em_adx_high = 40.0 - atr_pct * 0.10             # range ~30–40
        em_adx_high = max(em_adx_high, em_adx_low + 5)  # ensure window >= 5
        # EM: ATR compression — quiet markets accept higher pct, active need genuine compression
        em_atr_compression = 80.0 - atr_pct * 0.30      # range ~50–80
        # EM: CVD buildup bars — active markets need more confirmation
        em_cvd_bars = 2 if atr_pct < 50 else 3
        # MR: sweep window — quiet markets need wider window to catch sweeps
        mr_sweep_window = 7 if atr_pct < 30 else (5 if atr_pct < 70 else 4)

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
            cb_adx_max=cb_adx_max,
            em_adx_low=em_adx_low,
            em_adx_high=em_adx_high,
            em_atr_compression_pct=em_atr_compression,
            em_cvd_bars=em_cvd_bars,
            mr_sweep_window=mr_sweep_window,
        )
        await self.cache.update_adaptive(symbol, params)

    # -- WebSocket setup ----------------------------------------------------

    def _init_symbols(self) -> None:
        for s in self.symbols:
            self.cache.init_symbol(s)

    async def _start_ws(self, testnet: bool) -> None:
        # Pre-create LocalOrderBooks so diff events start buffering from first WS message.
        # Per Binance docs: open the stream FIRST, then fetch the REST snapshot.
        for s in self.symbols:
            if s not in self._order_books:
                self._order_books[s] = LocalOrderBook()

        self._ws = BinanceWS(testnet=testnet)
        for s in self.symbols:
            sl = s.lower()
            self._ws.subscribe(f"{sl}@kline_1m", self._make_kline_handler(s, "1m"))
            self._ws.subscribe(f"{sl}@kline_3m", self._make_kline_handler(s, "3m"))
            self._ws.subscribe(f"{sl}@kline_5m", self._make_kline_handler(s, "5m"))
            self._ws.subscribe(f"{sl}@bookTicker", self._make_book_handler(s))
            self._ws.subscribe(f"{sl}@aggTrade", self._make_agg_handler(s))
            self._ws.subscribe(f"{sl}@depth@100ms", self._make_depth_handler(s))
        await self._ws.start()

        # Wait for WS to connect and buffer some diff events, then fetch snapshots
        # concurrently so init_snapshot can find a valid straddling event in the buffer.
        await asyncio.sleep(1.0)
        await asyncio.gather(*[self._fetch_depth_snapshot(s) for s in self.symbols])

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

        # Don't remove symbols with open positions or pending orders
        open_syms = set(self.trader.positions.keys())
        if hasattr(self.trader, "pending"):
            open_syms |= set(self.trader.pending.keys())
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

    async def _fetch_depth_snapshot(self, symbol: str) -> None:
        """Fetch REST depth snapshot and initialise the LocalOrderBook."""
        try:
            data = await self.client.get_depth(symbol, limit=500)
            if not data or "lastUpdateId" not in data:
                logger.warning(f"Empty depth snapshot for {symbol}")
                return
            ob = self._order_books.setdefault(symbol, LocalOrderBook())
            ob.init_snapshot(data)
            # Seed cache immediately so first tick has depth data
            await self.cache.update_depth(symbol, ob.sorted_bids(), ob.sorted_asks())
            logger.debug(
                f"Depth snapshot {symbol}: lastUpdateId={data['lastUpdateId']}, "
                f"bids={len(data['bids'])}, asks={len(data['asks'])}"
            )
        except Exception:
            logger.exception(f"Failed to fetch depth snapshot for {symbol}")

    def _make_depth_handler(self, symbol: str) -> Any:
        async def handler(data: dict[str, Any]) -> None:
            ob = self._order_books.get(symbol)
            if ob is None:
                return
            ob.apply_diff(data)
            if not ob.initialized:
                return
            await self.cache.update_depth(symbol, ob.sorted_bids(), ob.sorted_asks())
        return handler

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _class_to_setup(cls_name: str) -> str:
        mapping = {
            "ContinuationBreak": "CONTINUATION_BREAK",
            "MeanReversion": "MEAN_REVERSION",
            "EarlyMomentum": "EARLY_MOMENTUM",
            "WallBounce": "WALL_BOUNCE",
        }
        return mapping.get(cls_name, cls_name)

    # -- user data stream (live mode only) ----------------------------------

    async def _start_user_data_stream(self) -> None:
        """Start Binance user data WS for ORDER_TRADE_UPDATE events."""
        try:
            self._listen_key = await self.client.create_listen_key()
            if not self._listen_key:
                logger.error("Failed to create listen key for user data stream")
                return

            self._user_ws = BinanceWS(testnet=self._testnet)
            self._user_ws.subscribe(
                self._listen_key,
                self._handle_user_data,
            )
            await self._user_ws.start()
            # Keepalive every 30 min
            self._listen_key_task = asyncio.create_task(
                self._keepalive_loop(),
            )
            logger.info("User data stream started")
        except Exception:
            logger.exception("Failed to start user data stream")

    async def _keepalive_loop(self) -> None:
        """Send keepalive for listen key every 30 minutes."""
        while self._running:
            await asyncio.sleep(30 * 60)
            try:
                await self.client.keepalive_listen_key()
                logger.debug("Listen key keepalive sent")
            except Exception:
                logger.warning("Listen key keepalive failed, recreating")
                try:
                    self._listen_key = await self.client.create_listen_key()
                except Exception:
                    logger.exception("Failed to recreate listen key")

    async def _handle_user_data(self, data: dict[str, Any]) -> None:
        """Route user data stream events to LiveTrader."""
        event_type = data.get("e", "")
        if event_type == "ORDER_TRADE_UPDATE":
            if hasattr(self.trader, "on_order_update"):
                await self.trader.on_order_update(data)
        elif event_type == "ACCOUNT_UPDATE":
            # Could track balance changes here
            pass
