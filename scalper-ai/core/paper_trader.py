from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from core.signal_generator import Direction, Position, Signal
from data.cache import MarketCache

if TYPE_CHECKING:
    from data.cache import MarketSnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRAILING_ACTIVATION_RR = 0.8  # activate trailing early — scalp, lock fast
TRAILING_PCT = 0.003          # 0.3% trailing — tight for quick capture
BREAKEVEN_TRIGGER_RR = 0.4    # move SL to entry at 0.4× risk (protect fast)
MAX_HOLD_MINUTES = 10         # SCALPING: 10 min max, catch the moment
SL_WIDEN_HIGH_VOL = 0.30      # 30% wider SL in HIGH_VOL
LEVERAGE = 25
CVD_EXIT_MIN_PNL_PCT = 0.003  # 0.3% profit enough for CVD exit in scalping
# Binance futures fees: maker 0.02%, taker 0.04%
MAKER_FEE = 0.0002  # limit orders (entry, TP)
TAKER_FEE = 0.0004  # market orders (SL by mark price, CVD exit, time stop)


class PaperTrader:
    """Simulates fills and position lifecycle in paper mode."""

    def __init__(self, cache: MarketCache) -> None:
        self.cache = cache
        self.positions: dict[str, Position] = {}

    @property
    def open_count(self) -> int:
        return len(self.positions)

    # -- open ---------------------------------------------------------------

    def open_position(self, signal: Signal, size_usdt: float) -> Position | None:
        # Sanity: TP must be on the correct side of entry
        if signal.direction == Direction.LONG and signal.tp_price <= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} <= entry {signal.entry_price}")
            return None
        if signal.direction == Direction.SHORT and signal.tp_price >= signal.entry_price:
            logger.warning(f"[PAPER] Rejected {signal.symbol}: TP {signal.tp_price} >= entry {signal.entry_price}")
            return None
        # size_usdt = position size (notional), NOT margin
        notional = size_usdt
        margin = notional / LEVERAGE
        sl_pct = abs(signal.entry_price - signal.sl_price) / signal.entry_price if signal.entry_price else 0
        pos = Position(
            signal=signal,
            symbol=signal.symbol,
            direction=signal.direction,
            setup_type=signal.setup_type,
            score=signal.score,
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            size_usdt=notional,
            quantity=notional / signal.entry_price if signal.entry_price else 0,
            best_price=signal.entry_price,
        )
        self.positions[signal.symbol] = pos
        logger.info(
            f"[PAPER] Opened {signal.direction.value} {signal.symbol} "
            f"@ {signal.entry_price:.6f} notional=${notional:.2f} "
            f"margin=${margin:.2f} sl_dist={sl_pct*100:.3f}%",
        )
        return pos

    # -- close --------------------------------------------------------------

    def close_position(
        self, symbol: str, price: float, reason: str,
    ) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        pos.current_pnl = self._calc_pnl(pos, price, reason)
        logger.info(
            f"[PAPER] Closed {symbol} @ {price:.6f} "
            f"pnl={pos.current_pnl:+.4f} reason={reason}",
        )
        return pos

    # -- update loop --------------------------------------------------------

    def update_positions(self) -> list[tuple[Position, str]]:
        """Tick all positions.  Returns list of (closed_pos, reason)."""
        closed: list[tuple[Position, str]] = []
        for symbol in list(self.positions):
            snap = self.cache.get_snapshot(symbol)
            if snap.stale or not snap.price:
                continue
            pos = self.positions[symbol]
            self._update_price_tracking(pos, snap.price)
            self._check_breakeven(pos, snap.price)
            self._check_trailing(pos, snap.price)
            reason = self._check_exits(pos, snap)
            if reason:
                p = self.close_position(symbol, snap.price, reason)
                if p:
                    closed.append((p, reason))
        return closed

    # -- sub-functions (≤50 lines each) -------------------------------------

    @staticmethod
    def _update_price_tracking(pos: Position, price: float) -> None:
        if pos.direction == Direction.LONG:
            pos.best_price = max(pos.best_price, price)
        else:
            pos.best_price = min(pos.best_price, price) if pos.best_price else price
        pos.current_pnl = PaperTrader._calc_pnl(pos, price)

    @staticmethod
    def _check_breakeven(pos: Position, price: float) -> None:
        if pos.breakeven_moved:
            return
        risk = abs(pos.entry_price - pos.sl_price)
        trigger = risk * BREAKEVEN_TRIGGER_RR
        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + trigger:
                pos.sl_price = pos.entry_price
                pos.breakeven_moved = True
        else:
            if price <= pos.entry_price - trigger:
                pos.sl_price = pos.entry_price
                pos.breakeven_moved = True

    @staticmethod
    def _check_trailing(pos: Position, price: float) -> None:
        risk = abs(pos.entry_price - pos.sl_price)
        rr_trigger = risk * TRAILING_ACTIVATION_RR
        if pos.direction == Direction.LONG:
            if price >= pos.entry_price + rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price * (1 - TRAILING_PCT)
                if trail_sl > pos.sl_price:
                    pos.sl_price = trail_sl
        else:
            if price <= pos.entry_price - rr_trigger:
                pos.trailing_activated = True
            if pos.trailing_activated:
                trail_sl = pos.best_price * (1 + TRAILING_PCT)
                if trail_sl < pos.sl_price:
                    pos.sl_price = trail_sl

    @staticmethod
    def _check_exits(pos: Position, snap: MarketSnapshot) -> str | None:
        price = snap.price
        # SL hit
        if pos.direction == Direction.LONG and price <= pos.sl_price:
            return "sl_hit"
        if pos.direction == Direction.SHORT and price >= pos.sl_price:
            return "sl_hit"
        # TP hit
        if pos.direction == Direction.LONG and price >= pos.tp_price:
            return "tp_hit"
        if pos.direction == Direction.SHORT and price <= pos.tp_price:
            return "tp_hit"
        # CVD divergence exit (only if min profit threshold met)
        pnl_pct = abs(price - pos.entry_price) / pos.entry_price if pos.entry_price else 0
        if pos.direction == Direction.LONG and snap.cvd_delta_1m < 0:
            if price > pos.entry_price and pnl_pct >= CVD_EXIT_MIN_PNL_PCT:
                return "cvd_divergence"
        if pos.direction == Direction.SHORT and snap.cvd_delta_1m > 0:
            if price < pos.entry_price and pnl_pct >= CVD_EXIT_MIN_PNL_PCT:
                return "cvd_divergence"
        # Time stop
        elapsed = (time.time() - pos.opened_at) / 60
        if elapsed >= MAX_HOLD_MINUTES:
            return "time_stop"
        return None

    @staticmethod
    def _calc_pnl(
        pos: Position, price: float, reason: str = "",
    ) -> float:
        # size_usdt is notional (full position), leverage already baked in
        if pos.direction == Direction.LONG:
            pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usdt
        else:
            pnl = (pos.entry_price - price) / pos.entry_price * pos.size_usdt
        # Entry: always limit (maker)
        entry_fee = pos.size_usdt * MAKER_FEE
        # Exit: TP = limit (maker), rest = market (taker)
        if reason == "tp_hit":
            exit_fee = pos.size_usdt * MAKER_FEE
        else:
            # sl_hit (stop-market by mark price), cvd_divergence, time_stop
            exit_fee = pos.size_usdt * TAKER_FEE
        return pnl - entry_fee - exit_fee
