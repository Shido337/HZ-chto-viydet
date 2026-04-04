# SCALPER-AI — Project Instructions

## Project Overview

This is a production-grade Binance USDT-M perpetual futures scalping bot with a React/TypeScript dashboard. The bot uses 25x isolated margin leverage and Order Flow Confluence Scalping (OFCS) methodology.

## Architecture

- **Backend**: Python 3.11+, async (asyncio), FastAPI, SQLAlchemy async, Loguru
- **Frontend**: React 18 + TypeScript + Vite + Zustand + TradingView Lightweight Charts
- **Exchange**: Binance Futures REST + WebSocket (aiohttp)
- **Database**: SQLite via aiosqlite

## Core Philosophy

We are building a **perfect-signal generator**, NOT a bad-signal blocker. Every module optimizes for signal quality, not signal suppression.

## Data Flow (one-way, no cycles)

```
WS Streams → MarketCache → MarketSnapshot → Strategies → Signal → BotEngine → Trader → Exchange
                                                                                  ↓
                                                                             Dashboard (read-only)
```

## Key Rules

1. **MarketCache** (`data/cache.py`) is the single source of truth for all market data. No module stores market data locally.
2. WebSocket handlers write to cache. Strategies READ from cache (immutable `MarketSnapshot`).
3. All writes to cache use `asyncio.Lock` per symbol.
4. Strategies receive `MarketSnapshot` — an immutable copy at a point in time.
5. PaperTrader and LiveTrader share identical public interfaces, swappable by BotEngine.
6. `workingType="MARK_PRICE"` on ALL protective orders (SL/TP/trailing).
7. `reduceOnly=True` on ALL SL/TP orders.
8. GTX post-only entry policy with FOK fallback on reject.
9. If SL placement fails after entry → IMMEDIATELY market close.
10. Never close position without first cancelling SL/TP orders.
11. All trades: isolated margin, 25x leverage.

## 3 Strategy Types

| Setup | Regime | Key Conditions |
|-------|--------|---------------|
| CONTINUATION_BREAK | TRENDING (ADX>25) | Structure break + CVD expansion + OB≥60% + volume spike |
| MEAN_REVERSION | RANGING/LOW_VOL (ADX<20) | Liquidity sweep + CVD reversal + bid/ask flip + wick rejection |
| EARLY_MOMENTUM | TRANSITIONING (ADX 20-25) | ATR compression + CVD buildup + OB consistency + price coiling |

## Signal Scoring (0.0–1.0, minimum 0.65 to trade)

- CVD alignment: 0–0.25
- Order book imbalance: 0–0.20
- Volume confirmation: 0–0.15
- Structure quality: 0–0.15
- Regime match: 0–0.15
- ML boost: 0–0.10

## Position Sizing Modes

- **FIXED**: static notional USDT
- **ADAPTIVE**: base × score multiplier × regime modifier
- **PERCENT**: balance % × score multiplier

## Risk Guards

- Max 20% of portfolio per position
- Max 5 simultaneous positions
- Daily loss limit: -15% of session start balance
- Every trade must have SL

## Commit Protocol

Every change must be committed via `utils/git_helper.py` — appends to CHANGELOG.md, stages files, commits, pushes.
