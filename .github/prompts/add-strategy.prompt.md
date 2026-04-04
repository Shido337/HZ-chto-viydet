---
description: "Add a new trading strategy to the SCALPER-AI bot. Creates strategy file, adds to BotEngine, and writes tests."
---

# Add New Strategy

## Inputs
- **Strategy Name**: e.g. `VOLUME_CLIMAX`
- **Regime**: Which MarketRegime(s) it fires in
- **Conditions**: List of ALL conditions that must be true

## Steps

1. Create `scalper-ai/strategies/{{name_snake}}.py`:
   - Import `BaseStrategy`, `Signal`, `MarketSnapshot`
   - Define threshold constants at module top
   - Implement `compute_signal()` → `Optional[Signal]`
   - Follow the pattern in `continuation_break.py`

2. Register in `scalper-ai/core/bot_engine.py`:
   - Import the new strategy class
   - Add to `self.strategies` list

3. Add to `scalper-ai/strategies/__init__.py` exports

4. Create `scalper-ai/tests/test_{{name_snake}}.py`:
   - Test signal generation with valid snapshot
   - Test rejection for each missing condition
   - Test score components are within expected ranges

5. Add setup type to dashboard `types/index.ts` → `SetupType` union

6. Commit via `git_helper.log_and_commit()`
