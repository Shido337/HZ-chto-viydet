---
description: "Tune strategy parameters, signal scoring weights, risk limits, or regime thresholds in the SCALPER-AI bot. Ensures changes are tested and committed."
---

# Tune Parameters

## Inputs
- **What to tune**: strategy thresholds, scoring weights, risk limits, or regime bounds
- **New values**: specific values or direction ("relax", "tighten")

## Steps

1. Identify the file and constants to modify:
   - Strategy thresholds → `strategies/continuation_break.py` etc. (top-level constants)
   - Scoring weights → `strategies/base_strategy.py` `score_components()`
   - Risk limits → `core/risk_manager.py` constants + `RiskConfig`
   - Regime bounds → `core/regime_classifier.py` `ADX_RANGING`, `ADX_TRANSITIONING`
   - Min signal score → `core/bot_engine.py` `MIN_SIGNAL_SCORE`

2. Update the constant value(s)

3. Check downstream impact:
   - Does this change any test expectations?
   - Does the dashboard display any of these values?

4. Run tests: `cd scalper-ai && python -m pytest tests/ -v`

5. Commit with descriptive message explaining WHY the tuning was done
