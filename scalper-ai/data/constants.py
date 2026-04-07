"""Shared constants used across multiple modules.

Single source of truth — import from here, never redefine elsewhere.
"""

# ---------------------------------------------------------------------------
# Exchange fees (Binance USDT-M Futures)
# ---------------------------------------------------------------------------
MAKER_FEE: float = 0.0002   # 0.02% limit orders (entry, TP)
TAKER_FEE: float = 0.0004   # 0.04% market orders (SL, CVD exit, time stop)

# ---------------------------------------------------------------------------
# Leverage
# ---------------------------------------------------------------------------
LEVERAGE: int = 25

# ---------------------------------------------------------------------------
# Risk global cap (all strategies + global SL clip)
# ---------------------------------------------------------------------------
GLOBAL_MAX_SL_PCT: float = 0.008   # 0.8% max SL distance for any trade

# ---------------------------------------------------------------------------
# Trailing / breakeven fallbacks (used when ATR is 0)
# ---------------------------------------------------------------------------
BREAKEVEN_TRIGGER_RR: float   = 0.6   # BE trigger = 0.6× initial risk
TRAILING_ACTIVATION_RR: float = 0.5   # activate trailing at 0.5× initial risk profit
TRAILING_RISK_FACTOR: float   = 0.4   # trail distance = 40% of initial risk
MIN_TRAIL_PCT: float          = 0.0003  # 0.03% absolute minimum trail distance

# ---------------------------------------------------------------------------
# CVD divergence exit thresholds (paper and live must be identical)
# ---------------------------------------------------------------------------
CVD_EXIT_MIN_PNL_PCT: float  = 0.002   # 0.2% min unrealized profit before CVD exit
CVD_EXIT_MIN_ATR_MULT: float = 0.3     # OR profit ≥ 0.3× ATR (whichever triggers first)
CVD_EXIT_MIN_HOLD_SEC: int   = 60      # hold ≥ 60 s before allowing CVD exit

# ---------------------------------------------------------------------------
# Per-setup max hold times (minutes)
# ---------------------------------------------------------------------------
MAX_HOLD_CB:  int = 15   # CB retest can consolidate before continuation
MAX_HOLD_EM:  int = 3    # EM is momentum — fire fast or bail
MAX_HOLD_MR:  int = 6    # MR sweep fade — medium window
MAX_HOLD_WB:  int = 3    # WB wall edge is short-lived — exit fast

# ---------------------------------------------------------------------------
# Wall bounce / absorption
# ---------------------------------------------------------------------------
WB_ABSORPTION_THRESHOLD: float = 0.50  # ≥50% wall qty absorbed = thesis confirmed/broken
