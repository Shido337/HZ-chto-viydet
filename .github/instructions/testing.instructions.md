---
description: "Use when writing or modifying tests in scalper-ai/tests/. Covers pytest patterns, async tests, fixture conventions, and what to test for each module."
applyTo: "scalper-ai/tests/**/*.py"
---

# Testing Standards — SCALPER-AI

## Framework

- pytest + pytest-asyncio
- Config in `pyproject.toml`: `asyncio_mode = "auto"`
- `conftest.py` adds project root to sys.path

## File Naming

- `tests/test_[module].py` — one test file per module
- Classes: `TestClassName` (no `__init__`)
- Methods: `test_descriptive_name`
- Use `setup_method` for per-test fixtures

## Async Tests

```python
@pytest.mark.asyncio
async def test_update_kline(self):
    cache = MarketCache()
    cache.init_symbol("BTCUSDT")
    await cache.update_kline("BTCUSDT", "1m", candle)
```

## What To Test

### indicators.py
- Each indicator returns correct type and reasonable range
- Edge cases: empty input, single value, insufficient data
- Known values: RSI trending up > 70, trending down < 30

### risk_manager.py
- All 3 size modes: FIXED, ADAPTIVE, PERCENT
- Score multipliers applied correctly
- Regime modifiers (HIGH_VOL × 0.50, LOW_VOL × 0.75)
- Cap at max_position_pct
- Daily loss limit triggers correctly
- Max positions enforcement

### cache.py
- init_symbol idempotent (doesn't reset existing data)
- get_snapshot returns correct values after updates
- Async update methods: kline, book, cvd, regime
- Default snapshot values for uninitialized symbol

### regime_classifier.py
- Strong trend → TRENDING_BULL or HIGH_VOL
- Flat market → RANGING or LOW_VOL
- Insufficient data → RANGING fallback

### online_learner.py
- No boost with insufficient samples
- High win rate → positive boost
- All losses → zero boost
- Drift detection when recent ≠ overall

## Rules

- No mocking exchange API in unit tests — test logic only
- Use `pytest.approx()` for float comparisons
- Each test is independent — no test order dependency
- Use dataclass mocks (not MagicMock) for Position/Signal
