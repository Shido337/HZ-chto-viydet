from __future__ import annotations

import pytest

from ml.online_learner import OnlineLearner


class TestOnlineLearner:
    def setup_method(self):
        self.ml = OnlineLearner()

    def test_no_boost_when_insufficient_data(self):
        boost = self.ml.predict_boost("CONTINUATION_BREAK", "BTCUSDT")
        assert boost == 0.0

    def test_boost_after_enough_wins(self):
        for _ in range(25):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", True)
        boost = self.ml.predict_boost("CONTINUATION_BREAK", "BTCUSDT")
        assert boost > 0.05  # High win rate → high boost

    def test_no_boost_after_losses(self):
        for _ in range(25):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", False)
        boost = self.ml.predict_boost("CONTINUATION_BREAK", "BTCUSDT")
        assert boost == 0.0

    def test_stats_accuracy(self):
        for _ in range(10):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", True)
        for _ in range(10):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", False)
        stats = self.ml.get_stats()
        assert stats["accuracy"] == 50.0

    def test_drift_detection(self):
        # First 30 wins
        for _ in range(30):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", True)
        stats = self.ml.get_stats()
        assert stats["drift"] == "Stable"
        # Then 20 losses — recent should differ from overall
        for _ in range(20):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", False)
        stats = self.ml.get_stats()
        assert stats["drift"] == "Drifting"

    def test_stats_structure(self):
        for _ in range(5):
            self.ml.record("CONTINUATION_BREAK", "BTCUSDT", True)
        stats = self.ml.get_stats()
        assert stats["samples"] == 5
        assert stats["accuracy"] == 100.0
        assert stats["drift"] == "Insufficient"
