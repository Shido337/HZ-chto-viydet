# SCALPER-AI CHANGELOG

## [2026-04-04 01:00 UTC]
Tighten EarlyMomentum: CVD bars 1->3, OB 52->58%, trend EMA filter, proximity 1.5->1.0%
Files: strategies/early_momentum.py

## [2026-04-04 07:11 UTC]
Scalp reality fix: TP 1.5/1.2/1.618 (was 3/2/2.618), trail 0.3RR/0.15%, BE 0.2RR, 5min hold, CVD exit 0.1%
Files: strategies/continuation_break.py, strategies/mean_reversion.py, strategies/early_momentum.py, core/paper_trader.py
