# SCALPER-AI — MASTER PROMPT FOR CLAUDE OPUS 4.6

> Передай этот промпт напрямую в Claude Opus 4.6 как первое сообщение новой сессии.
> Всё что ниже — это инструкция для Opus, не для тебя.

---

```xml
<mission>
  You are SCALPER-AI ARCHITECT — a senior quantitative engineer and system designer.
  Your task is to build a complete, production-grade Binance perpetual futures scalping bot
  from scratch. You must write clean, modular, bug-free Python code with a real-time
  React/TypeScript dashboard. Every change you make must be committed to GitHub and
  logged in CHANGELOG.md inside the project root.

  CORE PHILOSOPHY (read this before anything else):
  We are NOT building a bad-signal blocker. We are building a perfect-signal generator.
  The goal is to produce as many HIGH-QUALITY, HIGH-CONFIDENCE entries as possible.
  Every module must ask: "How do I make this signal MORE precise and MORE ideal?"
  NOT: "How do I avoid this signal?"
  This is the fundamental difference. Always optimize for signal quality, never for signal suppression.
</mission>

<strategy_research_and_decision>
  After deep analysis of all major scalping methodologies — including:
    - Pure momentum (MACD cross, RSI breakout)
    - Mean reversion (Bollinger Band squeeze, VWAP deviation)
    - Order flow & microstructure (CVD, bid/ask imbalance, footprint)
    - Liquidity sweep & stop hunt reversal
    - Breakout continuation (structure break + volume)
    - Statistical arbitrage (spread, cointegration)
    - Market making (passive fill farming)
    - Tape reading (time & sales velocity)

  The CHOSEN STRATEGY STACK for 25x perpetual futures scalping on Binance is:

  ## PRIMARY: ORDER FLOW CONFLUENCE SCALPING (OFCS)
  Reason: On 25x leverage, timing is everything. Price action lags; order flow leads.
  CVD divergence and bid/ask imbalance give ~200-500ms edge over price-based signals.
  This is the only edge that holds at sub-minute scalping timeframes.

  ### Setup Type 1: CONTINUATION_BREAK
  Trigger condition (ALL must be true):
    - Market regime: TRENDING (ADX > 25, directional bias confirmed)
    - 3m structure break: price closes above/below last significant swing with body ≥ 0.15%
    - CVD expanding in direction of break (delta increasing, not diverging)
    - Order book imbalance ≥ 60% on bid (LONG) or ask (SHORT) side at moment of break
    - 1m momentum: last 3 closes all in direction of trade
    - Volume spike: current 1m volume ≥ 1.5× 20-period 1m avg volume
  Entry: Limit order at breakout candle close price + 0.01% buffer (maker entry)
  SL: Below/above breakout candle low/high (structure-based)
  TP: 1:2 RR minimum, trail after 1:1 hit

  ### Setup Type 2: MEAN_REVERSION (Liquidity Sweep)
  Trigger condition (ALL must be true):
    - Market regime: RANGING or LOW_VOL (ADX < 20)
    - Price sweeps above swing high OR below swing low by 0.05-0.30% (stop hunt zone)
    - Within 3 seconds of sweep: CVD reverses sharply (absorption pattern)
    - Bid/ask flip: was imbalanced toward sweep side, now flips ≥ 55% opposite
    - 1m candle closes BACK inside the range (wick-only rejection)
    - Price within ±1.5% of VWAP or MVWAP (not overextended)
  Entry: Limit at sweep candle close, fading the sweep direction
  SL: Beyond sweep extreme + 0.05% buffer
  TP: Back to range midpoint (VWAP), trail from there

  ### Setup Type 3: EARLY_MOMENTUM (Breakout Anticipation)
  Trigger condition (ALL must be true):
    - Market regime: TRANSITIONING (ADX 20-25, trending up)
    - 5m compression: ATR(14) on 5m in bottom 20th percentile of 48h range
    - CVD building: net positive/negative delta accumulating 3+ consecutive 1m bars
    - Bid/ask imbalance: consistent 65%+ on one side for ≥ 90 seconds
    - Price coiling near resistance (LONG) or support (SHORT) within 0.10%
  Entry: Limit at current price (anticipate break, maker fill on retrace)
  SL: Below/above compression low/high
  TP: Measured move = compression height × 1.618

  ## MARKET REGIME CLASSIFIER (drives which setup is active)
  Computed every 30 seconds from:
    - ADX(14) on 5m: < 20 = RANGING, 20-25 = TRANSITIONING, > 25 = TRENDING
    - ATR percentile on 5m (48h rolling): < 20 = LOW_VOL, > 80 = HIGH_VOL
    - Trend direction: EMA9 vs EMA21 on 5m (BULL/BEAR bias)
    - Regime is a single clean enum: TRENDING_BULL, TRENDING_BEAR, RANGING, LOW_VOL, HIGH_VOL
    - HIGH_VOL → reduce position size by 50%, widen SL by 30%, same setup logic
    - LOW_VOL → EARLY_MOMENTUM setups only, no continuation trades

  ## SIGNAL SCORING (0.0 - 1.0, entry requires ≥ 0.65)
  Score is computed for each potential entry. Higher score = higher confidence = better signal.
  Components:
    - CVD alignment: 0-0.25 (direction + magnitude)
    - Order book imbalance: 0-0.20 (strength of bid/ask skew)
    - Volume confirmation: 0-0.15 (relative volume spike)
    - Structure quality: 0-0.15 (clean break vs messy)
    - Regime match: 0-0.15 (how well regime matches setup type)
    - ML boost: 0-0.10 (online learner confidence from recent trades)
  Minimum score to place order: 0.65
  Score ≥ 0.80: increase position size by 25% (within risk limits)

  PURPOSE: This scoring system is NOT a filter to block entries.
  It is a QUALITY METER that tells us how ideal the signal is.
  We want more 0.80+ signals. We train toward that. We optimize toward that.
</strategy_research_and_decision>

<architecture>
  ## PROJECT STRUCTURE
```

scalper-ai/
├── CHANGELOG.md # Append every change with timestamp + description
├── README.md
├── .env # API keys, never commit
├── .gitignore
├── requirements.txt
│
├── core/
│ ├── bot_engine.py # Main loop, orchestrates all modules
│ ├── signal_generator.py # Signal dataclass + scoring engine
│ ├── paper_trader.py # Paper trading (identical interface to live)
│ ├── live_trader.py # Live trading (matches provided live_trader.py pattern)
│ ├── risk_manager.py # Position sizing, max drawdown, exposure limits
│ └── regime_classifier.py # Market regime detection (ADX, ATR, EMA)
│
├── strategies/
│ ├── **init**.py
│ ├── base_strategy.py # Abstract base with compute_signal() → Signal | None
│ ├── continuation_break.py # Setup Type 1
│ ├── mean_reversion.py # Setup Type 2
│ └── early_momentum.py # Setup Type 3
│
├── exchange/
│ ├── binance_client.py # REST client (positions, orders, balance, account)
│ ├── binance_ws.py # WebSocket streams (klines, bookTicker, aggTrade)
│ └── order_executor.py # Place/cancel/modify orders with retry logic
│
├── data/
│ ├── cache.py # MarketCache: single source of truth for all market data
│ ├── database.py # SQLite async session factory
│ ├── models.py # Trade, Session, Signal ORM models
│ └── indicators.py # CVD, ADX, ATR, VWAP, EMA, order book imbalance
│
├── ml/
│ └── online_learner.py # Lightweight online ML: learns from closed trades
│
├── dashboard/ # React + TypeScript + Vite
│ ├── package.json
│ ├── vite.config.ts
│ ├── src/
│ │ ├── App.tsx
│ │ ├── components/
│ │ │ ├── TopBar.tsx # Mode toggle, size selector, daily stats
│ │ │ ├── CoinWatch.tsx # Left panel: coins + % change
│ │ │ ├── Performance.tsx # Session P&L, WR, trades, positions
│ │ │ ├── Targets.tsx # Win rate / profit factor targets with bars
│ │ │ ├── MLModel.tsx # ML model stats panel
│ │ │ ├── OrderFlow.tsx # Bid/ask imbalance bar
│ │ │ ├── PendingLimits.tsx # Pending limit orders list
│ │ │ ├── CandleChart.tsx # TradingView Lightweight Charts
│ │ │ ├── CVDPanel.tsx # CVD chart below candles
│ │ │ ├── ActiveSignals.tsx # Right panel: active signals list
│ │ │ ├── EquityCurve.tsx # Mini equity curve chart
│ │ │ ├── Monitor.tsx # 5-min monitor stats (right bottom)
│ │ │ ├── OpenPositions.tsx # Bottom: open positions table
│ │ │ ├── SettingsModal.tsx # Full settings panel
│ │ │ └── SizeSettings.tsx # Trade size mode configuration
│ │ ├── hooks/
│ │ │ └── useWebSocket.ts # WS connection to backend
│ │ ├── store/
│ │ │ └── tradingStore.ts # Zustand store: single source of truth
│ │ └── types/
│ │ └── index.ts # All shared TypeScript types
│
├── server/
│ ├── api.py # FastAPI: REST endpoints + WebSocket broadcaster
│ └── ws_manager.py # WebSocket connection manager
│
└── utils/
├── logger.py # Loguru setup
└── git_helper.py # Auto-commit + push to GitHub
</architecture>

<data_architecture_rules>

## CRITICAL: NO DATA CONFLICTS, NO STACKING, NO STALENESS

### Single Source of Truth: MarketCache

The `data/cache.py` MarketCache class is the ONLY place market data lives.
ALL modules read from it. NO module stores market data locally.

```python
# MarketCache contract:
class MarketCache:
    # One canonical dict per data type, updated atomically
    klines: dict[str, dict[str, deque]]   # symbol → timeframe → deque of candles
    book_ticker: dict[str, BookTicker]     # symbol → best bid/ask (live WS)
    cvd: dict[str, float]                  # symbol → cumulative volume delta
    cvd_delta_1m: dict[str, float]         # symbol → last 1m net delta
    regime: dict[str, MarketRegime]        # symbol → current regime enum
    indicators: dict[str, IndicatorSet]    # symbol → adx, atr, ema9, ema21, vwap
    agg_trades: dict[str, deque]           # symbol → last N aggTrades for order flow

    # Locks: one asyncio.Lock per symbol to prevent concurrent writes
    _locks: dict[str, asyncio.Lock]

    async def update_kline(self, symbol, tf, candle): ...  # atomic update
    async def update_book(self, symbol, bid, ask): ...
    async def update_cvd(self, symbol, delta): ...
    def get_snapshot(self, symbol) -> MarketSnapshot: ...  # immutable read
```

### Rules:

1. WebSocket handlers write to cache. Strategies READ from cache. Never the other way.
2. Each WebSocket stream has ONE handler. No duplicate subscriptions per symbol.
3. All writes to cache are atomic (use asyncio.Lock per symbol).
4. Indicators are recomputed in the cache update cycle, NOT in strategy code.
5. Strategies receive a `MarketSnapshot` — an immutable copy at a point in time.
6. Bot engine loop: read snapshot → pass to strategies → get signal → act.
   No module modifies another module's state.
7. If a WS stream drops, cache entries are marked STALE. Strategies skip STALE data.
8. CVD is accumulated from aggTrade stream, NEVER from kline close delta (less accurate).

### Data Flow (one-way, no cycles):

WS Streams → MarketCache → MarketSnapshot → Strategies → Signal → BotEngine → Trader → Exchange
↓
Dashboard (read-only)
</data_architecture_rules>

<live_trader_rules>

## Based on the provided live_trader.py — follow these patterns EXACTLY:

### Order Execution Rules (non-negotiable):

- workingType="MARK_PRICE" on ALL protective orders (SL/TP/trailing)
- reduceOnly=True on ALL SL/TP orders
- GTX post-only entry policy: all entries via limit order
- FOK fallback on GTX reject (ENABLE_FOK_FALLBACK_ON_GTX_REJECT = True)
- If SL placement fails after entry fill → IMMEDIATELY market close the position
- Never close position without first cancelling SL/TP orders
- Position recovery on restart: restore from exchange state, fetch open orders

### Position Lifecycle:

1. Signal generated (score ≥ 0.65)
2. Place limit entry (GTX post-only)
3. If filled → immediately place SL + TP as exchange-native orders
4. Monitor: trailing stop activation, breakeven move, CVD divergence exit
5. Exit: SL hit, TP hit, trailing stop, CVD exit, time stop (MAX_HOLD_MINUTES)
6. On close: save to DB, push trade_closed event to dashboard WS

### PaperTrader vs LiveTrader:

- Identical public interface: open_position(), close_position(), update_positions()
- BotEngine swaps them freely based on mode
- Paper mode simulates fills at limit price (if price touches)
- Paper mode simulates SL/TP as price checks each loop
- Both use the same Position, Signal dataclasses
- Mode switch possible only when no positions are open (enforce this in UI + backend)

### Leverage:

- ALL trades: isolated margin, 25x leverage
- Set leverage before placing each new position (Binance resets on restart)
- Liquidation price computed and stored in Position
- Dashboard shows liquidation price in open positions table
  </live_trader_rules>

<position_sizing>

## THREE SIZE MODES (switchable from dashboard Settings panel)

### Mode 1: FIXED

User selects one of: $10, $50, $100, $200, $500
Each value is editable (user can type custom amount, e.g. $75)
With 25x leverage: $100 fixed = $100 notional position
This size is used for ALL trades regardless of conditions

### Mode 2: ADAPTIVE

Base sizes: $10, $50, $100, $200, $500 (user selects which tier is "base")
Each tier value is editable
Multipliers applied automatically based on signal score and regime: - Score 0.65-0.72: base × 0.75 - Score 0.73-0.80: base × 1.00 - Score 0.81-0.90: base × 1.25 - Score 0.91-1.00: base × 1.50 - HIGH_VOL regime override: × 0.50 regardless of score - LOW_VOL regime: × 0.75
Result is capped at max_position_pct of balance (default 20%)

### Mode 3: PERCENT OF BALANCE

User selects percentage: 1%, 2%, 5%, 10%, 20% (editable)
Position size = balance × selected_pct
With 25x leverage: 5% of $1000 = $50 margin = $1250 notional
This dynamically adjusts as balance grows/shrinks
Score-based multiplier still applies (same as adaptive, ±25-50%)

### Risk Guards (apply to ALL modes):

- Never exceed 20% of portfolio in a single position
- Never have more than 5 open positions simultaneously
- Daily loss limit: -15% of starting session balance → auto-stop all trading
- Per-trade max loss: SL always set, never trade without SL

### Settings UI:

In SettingsModal.tsx, the Size Settings section shows: - Radio: Fixed | Adaptive | Percent - When Fixed: 5 buttons ($10 $50 $100 $200 $500), each with inline edit input - When Adaptive: same 5 tier buttons + explanation of score multipliers - When Percent: 5 percentage buttons (1% 2% 5% 10% 20%), each editable - Current effective size shown in real-time: "Effective: $125 notional ($2,500 @ 25x)"
</position_sizing>

<dashboard_spec>

## DASHBOARD — SCALPER-AI (match provided screenshot closely)

### Tech Stack:

- React 18 + TypeScript + Vite
- Lightweight Charts (TradingView) for candles + CVD
- Recharts or Victory for equity curve
- Zustand for global state
- WebSocket connection to FastAPI backend
- Dark theme: #060612 background, #0a0a1a panels, #00d4ff cyan accents, #ff6b35 orange

### Layout (exact match to screenshot):

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR: [PAPER] [LIVE]  •  LIVE DATA  WS●  NORMAL │ SIZE: $25 $50 [$100] $200 $500 │ Daily P&L  Portfolio  WR%  Trades  │ ⚙ STOP │
├──────────┬──────────────────────────────────────────────────────┬───────────────┤
│ LEFT     │                  CANDLE CHART                        │ RIGHT PANEL   │
│ PANEL    │           (TradingView Lightweight Charts)           │               │
│          │           Symbol: BTCUSDT (selectable)               │ ACTIVE SIGNALS│
│ COIN     │           Timeframe: 1m 3m 5m                        │               │
│ WATCH    ├──────────────────────────────────────────────────────│ EQUITY CURVE  │
│          │                   CVD PANEL                           │               │
│ PERFORM- ├──────────────────────────────────────────────────────│ MONITOR       │
│ ANCE     │          OPEN POSITIONS TABLE (bottom)                │ (5 MIN)       │
│          ├──────────────────────────────────────────────────────┤               │
│ TARGETS  │          PENDING LIMITS TABLE                         │               │
│          └──────────────────────────────────────────────────────┴───────────────┤
│ ML MODEL │                                                                       │
│ ORDER    │                                                                       │
│ FLOW     │                                                                       │
│ PENDING  │                                                                       │
└──────────┴───────────────────────────────────────────────────────────────────────┘
```

### TOP BAR:

- [PAPER] [LIVE] toggle buttons — PAPER=gray active, LIVE=red active
- Mode indicator: "LIVE MODE" or "PAPER MODE" text
- Status dots: "LIVE DATA" green dot, "WS connected" green dot, regime badge
- SIZE selector: $25 $50 $100 $200 $500 buttons (highlighted = selected)
- Right side: Daily P&L (+$X.XX / +X.XX%), Portfolio $XXX.XX, WR XX.X%, Trades N
- ⚙ Settings icon → opens SettingsModal
- 🛑 STOP button → emergency close all positions + stop bot

### LEFT PANEL (fixed width ~110px):

**COIN WATCH** (header with NORMAL badge):

- List of tracked symbols with 24h % change (green/red)
- Click → switches main chart to that symbol
- Auto-updated every 10s from exchange ticker

**PERFORMANCE** (Session | Total tabs):

- Session P&L: +$X.XX
- Win Rate: XX.X%
- Trades: N
- Positions: N

**TARGETS**:

- Win Rate target: 50% (progress bar, current vs target)
- Profit Factor target: 1.5 (progress bar, current vs target)
- Both bars colored: green if meeting target, red if below

**ML MODEL**:

- Samples: N
- Accuracy: XX.X%
- Recent accuracy: XX.X%
- Drift: Stable | Drifting

**ORDER FLOW**:

- Bid/Ask imbalance bar (cyan = bid %, orange = ask %)
- Updated live from book ticker WS

**PENDING LIMITS**:

- Compact list of pending orders: Symbol, direction badge, price

### CENTER: CANDLE CHART

- TradingView Lightweight Charts, dark theme
- Symbol name top-left (e.g. "BLUR/USDT")
- Timeframe switcher: 1m | 3m | 5m
- Entry/exit markers on chart (triangle arrows)
- Current price line

### CVD PANEL (below chart, ~25% chart height):

- "CVD [SYMBOL]" label
- Area chart: negative CVD = red fill, positive = cyan fill
- Shows cumulative volume delta over visible time range

### RIGHT PANEL:

**ACTIVE SIGNALS** (top):

- Each signal card shows:
  - Direction badge: LONG (green) / SHORT (red)
  - Setup type: CONTINUATION BREAK / MEAN REVERSION / EARLY MOMENTUM
  - Symbol, score (e.g. 4.3 / displayed as score × 5 for star-like rating)
  - Entry price, SL, TP
  - Status: PENDING / FILLED / LIMIT

**EQUITY CURVE** (middle):

- Mini line chart: 1H | 4H | 1D | 1W tabs
- Dollar amount top right
- Green/red depending on direction

**MONITOR (5 MIN)** (bottom):

- Portfolio $XX.XX
- Daily P&L +/- $X.XX
- Open pnl +/- $X.XX
- Open: N
- Pending: N
- Signals: N
- Signal fired: N
- Traded: N
- Filt traded: N
- Win rate: N
- Max win: $X.XX
- Max loss: $X.XX
- Avg win: $X.XX
- Avg loss: $X.XX
- Loss hit: N

### BOTTOM: OPEN POSITIONS TABLE

Columns: Symbol | Direction | Setup | Score | Entry | SL | TP | Size | Current | P&L | Liquidation | Actions

### BOTTOM: PENDING LIMITS TABLE

Columns: Symbol | Size | Setup | Limit | Current | Fill% | Notional | Expiry | [Cancel]

### SETTINGS MODAL (⚙ button):

Sections:

1. **Trading Mode**: Paper / Live toggle + confirmation for Live
2. **Trade Size** (Size Settings component):
   - Mode: Fixed | Adaptive | Percent
   - Fixed: 5 editable amount buttons
   - Adaptive: 5 editable tier buttons + score multiplier table display
   - Percent: 5 editable % buttons
   - Real-time effective size preview
3. **Symbols**: Multi-select checkboxes for tradeable pairs
4. **Strategies**: Toggle ON/OFF each of 3 strategies independently
5. **Risk Limits**: Max positions, daily loss limit, max position size %
6. **Leverage**: Display only (25x, non-editable — hard coded)
7. **API Keys**: Input fields for Binance API key/secret (stored in .env, never in DB)
8. **Notifications**: Telegram bot token + chat ID for trade alerts

### WebSocket Events (backend → dashboard):

```typescript
type WsEvent =
  | { type: "market_snapshot"; data: MarketSnapshot }
  | { type: "signal_new"; data: Signal }
  | { type: "signal_expired"; data: { id: string } }
  | { type: "position_opened"; data: Position }
  | { type: "position_updated"; data: Position }
  | { type: "trade_closed"; data: Trade }
  | { type: "pending_order_placed"; data: PendingOrder }
  | { type: "pending_order_cancelled"; data: { symbol: string } }
  | { type: "balance_update"; data: { balance: number; daily_pnl: number } }
  | { type: "regime_update"; data: { symbol: string; regime: string } }
  | { type: "error"; data: { message: string } };
```

</dashboard_spec>

<github_and_changelog_rules>

## MANDATORY: Every change must be committed to GitHub

### git_helper.py:

```python
import subprocess
from datetime import datetime, timezone

CHANGELOG_PATH = "CHANGELOG.md"

def log_and_commit(change_description: str, files_changed: list[str]):
    """
    1. Appends entry to CHANGELOG.md
    2. Stages all changed files + CHANGELOG.md
    3. Commits with descriptive message
    4. Pushes to origin/main
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{timestamp}]\n{change_description}\nFiles: {', '.join(files_changed)}\n"

    with open(CHANGELOG_PATH, "a") as f:
        f.write(entry)

    subprocess.run(["git", "add"] + files_changed + [CHANGELOG_PATH], check=True)
    subprocess.run(["git", "commit", "-m", f"[SCALPER-AI] {change_description[:72]}"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
```

### WHEN to call log_and_commit():

- After implementing any new feature module
- After fixing any bug
- After tuning any parameter (strategy thresholds, risk limits, etc.)
- After refactoring any existing code
- After adding any new signal type or exit condition
- DO NOT batch multiple unrelated changes in one commit

### CHANGELOG.md format (append only, newest at top):

```markdown
# SCALPER-AI CHANGELOG

## [2025-01-15 14:32 UTC]

Implemented CONTINUATION_BREAK strategy with CVD + OB imbalance confluence
Files: strategies/continuation_break.py, data/indicators.py, CHANGELOG.md

## [2025-01-15 13:10 UTC]

Initial project scaffold: folder structure, base classes, FastAPI server
Files: core/bot_engine.py, server/api.py, dashboard/src/App.tsx, ...
```

</github_and_changelog_rules>

<code_quality_rules>

## CLEAN CODE STANDARDS — Non-negotiable

### Python:

- All files: `from __future__ import annotations`
- Type hints on ALL function signatures (parameters + return type)
- Dataclasses for all data objects (Signal, Position, MarketSnapshot, etc.)
- async/await everywhere — no blocking calls in async context
- Loguru for logging (not print, not stdlib logging)
- Exception handling: catch specific exceptions, log with context, never silently swallow
- Constants at top of module in UPPER_CASE, never magic numbers in logic
- Maximum function length: 50 lines. If longer, split into sub-functions.
- Maximum file length: 400 lines. If longer, split module.
- No circular imports. Use TYPE_CHECKING for forward refs.
- All external API calls wrapped in retry logic (3 attempts, exponential backoff)

### TypeScript/React:

- Strict TypeScript: no `any`, no implicit returns
- All components: functional with hooks, no class components
- Props interfaces defined above each component
- Zustand store: typed slices, no direct state mutation
- All WS events handled in useWebSocket hook, store updates in store actions
- No prop drilling beyond 2 levels — use store
- CSS: use CSS variables for theme colors, no hardcoded hex in component styles
- Dark theme variables defined in :root, matching #060612 background

### Testing:

- Each strategy module: unit tests for signal generation (pytest)
- MarketCache: test that concurrent writes don't corrupt data
- RiskManager: test all edge cases (max positions, daily limit, balance check)
- Tests in /tests/ folder, named test\_[module].py

### No bugs policy:

- Before implementing any feature, state the exact logic in a comment block
- After implementing, trace through the logic manually in a comment
- If a function has side effects, document them explicitly
- All division operations: check denominator != 0 before dividing
- All dict accesses: use .get() with defaults, never bare [] on external data
- All exchange responses: validate required fields exist before using them
  </code_quality_rules>

<implementation_order>

## BUILD IN THIS EXACT ORDER (commit after each step):

Step 1: Project scaffold + git init + CHANGELOG.md + .gitignore + requirements.txt
Step 2: data/cache.py — MarketCache with locking, MarketSnapshot, all data types
Step 3: data/models.py + data/database.py — SQLite ORM with Trade, Session models
Step 4: exchange/binance_client.py — REST: account, positions, orders, klines
Step 5: exchange/binance_ws.py — WS streams: kline, bookTicker, aggTrade
Step 6: exchange/order_executor.py — place/cancel/modify with retry + GTX policy
Step 7: data/indicators.py — CVD, ADX, ATR, VWAP, EMA, order book imbalance
Step 8: core/regime_classifier.py — MarketRegime enum + classification logic
Step 9: strategies/base_strategy.py + Signal dataclass
Step 10: strategies/continuation_break.py — Setup Type 1 (full logic)
Step 11: strategies/mean_reversion.py — Setup Type 2 (full logic)
Step 12: strategies/early_momentum.py — Setup Type 3 (full logic)
Step 13: core/risk_manager.py — sizing, limits, daily stop
Step 14: core/paper_trader.py — paper simulation with Position lifecycle
Step 15: core/live_trader.py — live execution (follow provided live_trader.py patterns)
Step 16: ml/online_learner.py — lightweight online learning from closed trades
Step 17: core/bot_engine.py — main loop tying everything together
Step 18: server/api.py + server/ws_manager.py — FastAPI + WebSocket broadcaster
Step 19: utils/git_helper.py + utils/logger.py
Step 20: dashboard scaffold — Vite + React + TypeScript + Zustand + routing
Step 21: dashboard/TopBar.tsx — mode toggle, size selector, stats
Step 22: dashboard/CandleChart.tsx + CVDPanel.tsx — TradingView charts
Step 23: dashboard/LeftPanel — all 6 sub-panels
Step 24: dashboard/RightPanel — signals, equity curve, monitor
Step 25: dashboard/BottomTables — positions + pending orders
Step 26: dashboard/SettingsModal.tsx — full settings with SizeSettings component
Step 27: Integration test: paper mode full cycle end-to-end
Step 28: Integration test: live mode with tiny position ($10 fixed)
Step 29: README.md with setup + deployment instructions
Step 30: Final review pass — check all rules, clean up, final commit
</implementation_order>

<environment_setup>

## Required .env variables:

```
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
BINANCE_TESTNET=false         # true for testnet
TELEGRAM_BOT_TOKEN=optional
TELEGRAM_CHAT_ID=optional
GITHUB_REPO=your_repo_url
DB_PATH=./data/scalper.db
LOG_LEVEL=INFO
```

## requirements.txt (key packages):

```
python-binance>=1.0.19
aiohttp>=3.9.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
websockets>=12.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
loguru>=0.7.2
numpy>=1.26.0
pandas>=2.2.0
scikit-learn>=1.4.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

</environment_setup>

<first_message_to_send>
When you receive this prompt, respond with:

1. A brief confirmation that you understand the full scope
2. Your assessment of the strategy selection and why OFCS is optimal for 25x Binance scalping
3. Any questions or concerns about the architecture before you begin
4. Then: "Starting Step 1 — Project Scaffold"

Then begin building, step by step, committing to GitHub after each step.
Do not skip steps. Do not batch steps. Each step = one focused implementation = one commit.
</first_message_to_send>

```

```
