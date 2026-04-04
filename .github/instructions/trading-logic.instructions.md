---
description: "Use when modifying trading strategies, signal scoring, order execution, risk management, position sizing, or exchange integration. Covers OFCS methodology, regime classification, SL/TP rules, and GTX order policy."
---

# Trading Logic Rules — SCALPER-AI

## Order Execution — Non-Negotiable

- `workingType="MARK_PRICE"` on ALL protective orders (SL/TP/trailing)
- `reduceOnly=True` on ALL SL/TP orders
- GTX (post-only) entry → FOK fallback on GTX reject (code -5022)
- If SL placement fails after entry fill → IMMEDIATELY market close position
- Never close a position without first cancelling its SL/TP orders
- Set leverage (25x) + margin type (ISOLATED) before every new position

## Strategy Conditions — ALL Must Be True

### CONTINUATION_BREAK (ADX > 25, TRENDING)
1. 3m structure break: close beyond last swing, body ≥ 0.15%
2. CVD expanding in break direction (delta_1m same sign)
3. Order book imbalance ≥ 60% on entry side
4. Last 3 × 1m closes in direction
5. Volume spike ≥ 1.5× 20-period avg

### MEAN_REVERSION (ADX < 20, RANGING/LOW_VOL)
1. Price sweeps beyond swing by 0.05–0.30%
2. CVD reverses after sweep (absorption)
3. Bid/ask flips ≥ 55% opposite
4. 1m candle closes back inside range (wick rejection)
5. Price within ±1.5% of VWAP

### EARLY_MOMENTUM (ADX 20-25, TRANSITIONING)
1. 5m ATR in bottom 20th percentile (compression)
2. CVD building 3+ consecutive 1m bars
3. OB imbalance consistent 65%+ on one side
4. Price within 0.10% of key level

## Signal Scoring — Quality Meter

Score is NOT a filter. It's a quality meter. We optimize for MORE high-score signals.

| Component | Weight | Source |
|-----------|--------|--------|
| CVD alignment | 0–0.25 | cvd_delta_1m direction + magnitude |
| OB imbalance | 0–0.20 | bid_ask_imbalance strength |
| Volume confirmation | 0–0.15 | volume_ratio spike |
| Structure quality | 0–0.15 | body size, clean break |
| Regime match | 0–0.15 | how well regime fits setup |
| ML boost | 0–0.10 | OnlineLearner predict_boost() |

Minimum to trade: **0.65**. Score ≥ 0.80 → increase size by 25%.

## Regime Classifier

Recomputed every 30 seconds from 5m candles:
- ADX(14) < 20 → RANGING
- ADX(14) 20-25 → TRANSITIONING (maps to RANGING enum, EARLY_MOMENTUM can fire)
- ADX(14) > 25 → TRENDING_BULL or TRENDING_BEAR (EMA9 vs EMA21)
- ATR percentile < 20 → LOW_VOL
- ATR percentile > 80 → HIGH_VOL

## Risk — Hard Limits

- Max position: 20% of balance
- Max open: 5 positions
- Daily loss: -15% of session start → auto-stop
- HIGH_VOL → size × 0.50
- LOW_VOL → size × 0.75
- Time stop: MAX_HOLD_MINUTES = 10

## Data Flow

MarketCache is the single source of truth. No module stores market data locally.
Strategies get immutable `MarketSnapshot`. One-way flow: WS → Cache → Strategy → Signal → Engine.
