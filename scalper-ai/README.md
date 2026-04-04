# SCALPER-AI

Production-grade Binance USDT-M perpetual futures scalping bot with a real-time React/TypeScript dashboard. Uses **Order Flow Confluence Scalping (OFCS)** methodology with 25x isolated margin leverage.

## Architecture

```
WS Streams → MarketCache → MarketSnapshot → Strategies → Signal → BotEngine → Trader → Exchange
                                                                                  ↓
                                                                           Dashboard (read-only)
```

- **Backend**: Python 3.11+, async (asyncio), FastAPI, SQLAlchemy async, Loguru
- **Frontend**: React 18 + TypeScript + Vite + Zustand + TradingView Lightweight Charts
- **Exchange**: Binance Futures REST + WebSocket (aiohttp)
- **Database**: SQLite via aiosqlite

## Strategy Stack

| Setup | Regime | Key Conditions |
|-------|--------|----------------|
| **CONTINUATION_BREAK** | TRENDING (ADX > 25) | Structure break + CVD expansion + OB ≥ 60% + volume spike |
| **MEAN_REVERSION** | RANGING / LOW_VOL (ADX < 20) | Liquidity sweep + CVD reversal + bid/ask flip + wick rejection |
| **EARLY_MOMENTUM** | TRANSITIONING (ADX 20–25) | ATR compression + CVD buildup + OB consistency + price coiling |

Signal scoring from 0.0–1.0 (minimum 0.65 to trade). Components: CVD alignment (0.25), OB imbalance (0.20), volume (0.15), structure (0.15), regime match (0.15), ML boost (0.10).

## Prerequisites

- Python 3.11+
- Node.js 18+
- Git

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd scalper-ai
```

### 2. Python environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment variables

Create a `.env` file in the `scalper-ai/` directory:

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
BINANCE_TESTNET=true
TELEGRAM_BOT_TOKEN=optional
TELEGRAM_CHAT_ID=optional
GITHUB_REPO=your_repo_url
DB_PATH=./data/scalper.db
LOG_LEVEL=INFO
```

Set `BINANCE_TESTNET=true` for paper/testnet mode, `false` for live mainnet.

### 4. Dashboard setup

```bash
cd dashboard
npm install
cd ..
```

## Running

### Start the backend (FastAPI server)

```bash
cd scalper-ai
uvicorn server.api:app --host 0.0.0.0 --port 8000 --reload
```

### Start the dashboard (Vite dev server)

```bash
cd scalper-ai/dashboard
npm run dev
```

The dashboard will be available at `http://localhost:3000` and proxies API/WS calls to the backend at `http://localhost:8000`.

### Run both together (production)

Build the dashboard first:

```bash
cd scalper-ai/dashboard
npm run build
```

Then serve the static files from FastAPI or use a reverse proxy (nginx).

## Configuration

### Trading Mode

- **Paper Mode** (default): Simulates trades locally without touching the exchange.
- **Live Mode**: Executes real orders on Binance Futures. Switch via the dashboard toggle or `POST /api/mode/live`.

Mode can only be switched when no positions are open.

### Position Sizing

Three modes available in Settings:

| Mode | Description |
|------|-------------|
| **FIXED** | Static notional USDT ($10, $50, $100, $200, $500 — editable) |
| **ADAPTIVE** | Base × score multiplier × regime modifier |
| **PERCENT** | Balance % × score multiplier (1%, 2%, 5%, 10%, 20%) |

Score multipliers (Adaptive & Percent):
- 0.65–0.72 → 0.75×
- 0.73–0.80 → 1.00×
- 0.81–0.90 → 1.25×
- 0.91–1.00 → 1.50×
- HIGH_VOL regime → 0.50×
- LOW_VOL regime → 0.75×

### Risk Guards

- Max 20% of portfolio per position
- Max 5 simultaneous positions
- Daily loss limit: -15% of session start balance → auto-stop
- Every trade must have SL

### Symbols

Default: BTCUSDT, ETHUSDT. Add more via the Settings modal.

### Strategies

Each of the 3 strategies can be independently enabled/disabled in Settings.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Bot status, mode, symbols, strategy toggles |
| GET | `/api/positions` | Open positions list |
| GET | `/api/balance` | Balance, daily P&L, session start |
| GET | `/api/ml/stats` | ML model statistics |
| GET | `/api/signals` | Active signals list |
| GET | `/api/settings` | Current settings |
| POST | `/api/mode/{mode}` | Switch paper/live |
| POST | `/api/stop` | Emergency close all positions |
| POST | `/api/settings` | Update settings |
| WS | `/ws` | Real-time events stream |

### WebSocket Events

```
market_snapshot, signal_new, signal_expired, position_opened,
position_updated, trade_closed, pending_order_placed,
pending_order_cancelled, balance_update, regime_update, error
```

## Monitoring & Logging

- Logs are written to `logs/scalper_YYYY-MM-DD.log` with 50MB rotation
- Console output with colored levels
- Dashboard Monitor panel shows real-time stats (portfolio, P&L, win rate, etc.)

## Testing

```bash
cd scalper-ai
python -m pytest tests/ -v --tb=short
```

Tests cover:
- `test_indicators.py` — All technical indicators (EMA, ATR, ADX, RSI, VWAP, Bollinger Bands, CVD, OB imbalance, ATR percentile, swing detection)
- `test_cache.py` — MarketCache atomicity, snapshot immutability, stale marking
- `test_regime.py` — Regime classification across all market conditions
- `test_risk_manager.py` — Position sizing, risk guards, daily limits
- `test_ml.py` — Online learner recording, prediction, stats
- `test_strategies.py` — All 3 strategy signal generation with realistic snapshots

## Project Structure

```
scalper-ai/
├── CHANGELOG.md          # Auto-generated change log
├── README.md             # This file
├── .env                  # API keys (never commit)
├── requirements.txt      # Python dependencies
├── core/                 # Engine, traders, risk, regime, signals
├── strategies/           # CONTINUATION_BREAK, MEAN_REVERSION, EARLY_MOMENTUM
├── exchange/             # Binance REST client, WebSocket, order executor
├── data/                 # MarketCache, database, models, indicators
├── ml/                   # Lightweight online ML learner
├── server/               # FastAPI REST + WebSocket server
├── dashboard/            # React + TypeScript + Vite frontend
├── tests/                # pytest test suite
└── utils/                # Logger, git helper
```

## Troubleshooting

### WebSocket disconnects

Check that the backend is running and Binance WS streams are accessible. Testnet WS endpoints may differ. The dashboard auto-reconnects after 3 seconds.

### "Daily loss limit hit"

Trading auto-stops when daily P&L drops below -15% of session start balance. Restart the bot to reset the session.

### Mode switch blocked

Close all open positions before switching between Paper and Live mode.

### Missing kline data

Strategies require at least 16 candles of 5m data for regime classification. Wait 80+ minutes after starting for full indicator warmup, or pre-seed klines from REST API on startup.

## License

Private — internal use only.
