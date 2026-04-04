from __future__ import annotations

import pytest

from core.risk_manager import RiskManager, SizeMode
from data.cache import MarketRegime


class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager()
        self.rm.mode = SizeMode.FIXED
        self.rm.fixed_amount = 100.0
        self.rm.session_start_balance = 1000.0

    def test_fixed_size(self):
        size = self.rm.compute_size(1000.0, 0.80, MarketRegime.RANGING, 0)
        assert size == 100.0

    def test_high_vol_reduction(self):
        # FIXED mode: no regime modifier, always fixed
        size = self.rm.compute_size(1000.0, 0.80, MarketRegime.HIGH_VOL, 0)
        assert size == 100.0  # FIXED = always 100

    def test_low_vol_reduction(self):
        # FIXED mode: no regime modifier, always fixed
        size = self.rm.compute_size(1000.0, 0.80, MarketRegime.LOW_VOL, 0)
        assert size == 100.0  # FIXED = always 100

    def test_cap_at_max_position_pct(self):
        rm = RiskManager()
        rm.mode = SizeMode.FIXED
        rm.fixed_amount = 500.0
        rm.session_start_balance = 1000.0
        size = rm.compute_size(100.0, 0.80, MarketRegime.RANGING, 0)
        assert size == 20.0  # 100 * 0.20

    def test_adaptive_score_multiplier(self):
        rm = RiskManager()
        rm.mode = SizeMode.ADAPTIVE
        rm.adaptive_base = 100.0
        rm.session_start_balance = 10000.0
        # Score 0.85 → multiplier 1.25
        size = rm.compute_size(10000.0, 0.85, MarketRegime.TRENDING_BULL, 0)
        assert size == 125.0

    def test_percent_mode(self):
        rm = RiskManager()
        rm.mode = SizeMode.PERCENT
        rm.percent_value = 5.0
        rm.session_start_balance = 2000.0
        # Balance 2000, 5% = 100, score 0.75 → mult 1.0
        size = rm.compute_size(2000.0, 0.75, MarketRegime.RANGING, 0)
        assert size == 100.0

    def test_daily_limit(self):
        assert not self.rm.check_daily_limit()
        self.rm.daily_pnl = -150.0  # -15%
        assert self.rm.check_daily_limit()

    def test_max_positions_blocks(self):
        # open_count >= MAX_OPEN_POSITIONS → returns 0
        size = self.rm.compute_size(1000.0, 0.80, MarketRegime.RANGING, 5)
        assert size == 0.0

    def test_reset_daily(self):
        self.rm.daily_pnl = -200.0
        assert self.rm.check_daily_limit()
        self.rm.daily_pnl = 0.0
        assert not self.rm.check_daily_limit()
