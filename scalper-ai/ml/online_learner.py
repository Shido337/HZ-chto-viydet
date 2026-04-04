from __future__ import annotations

from collections import defaultdict

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_SAMPLES = 10
RECENT_WINDOW = 20
MAX_BOOST = 0.10
DRIFT_THRESHOLD = 0.15  # |recent_wr - overall_wr| > this → drifting

# Score adjustment bounds
SCORE_LOWER_MAX = -0.08   # max loosening when performing well
SCORE_RAISE_MAX = 0.12    # max tightening when performing poorly
NEUTRAL_WR = 0.45         # win rate considered neutral (no adjustment)


class OnlineLearner:
    """Lightweight per-(setup, symbol) win-rate tracker with drift detection."""

    def __init__(self) -> None:
        self._wins: dict[str, int] = defaultdict(int)
        self._total: dict[str, int] = defaultdict(int)
        self._recent: dict[str, list[bool]] = defaultdict(list)

    # -- record outcome -----------------------------------------------------

    def record(self, setup_type: str, symbol: str, won: bool) -> None:
        key = f"{setup_type}:{symbol}"
        self._total[key] += 1
        if won:
            self._wins[key] += 1
        self._recent[key].append(won)
        if len(self._recent[key]) > RECENT_WINDOW:
            self._recent[key] = self._recent[key][-RECENT_WINDOW:]

    # -- predict boost 0.0–0.10 --------------------------------------------

    def predict_boost(self, setup_type: str, symbol: str) -> float:
        key = f"{setup_type}:{symbol}"
        total = self._total.get(key, 0)
        if total < MIN_SAMPLES:
            return 0.0
        wr = self._wins[key] / total
        if wr <= 0.5:
            return 0.0
        return min((wr - 0.5) * 0.20, MAX_BOOST)

    # -- score adjustment for adaptive params --------------------------------

    def get_score_adjustment(self, setup_type: str, symbol: str) -> float:
        """Return delta for min_score: negative = loosen, positive = tighten.

        Uses recent window for responsiveness.  Returns 0.0 until enough
        samples are collected.
        """
        key = f"{setup_type}:{symbol}"
        recent = self._recent.get(key, [])
        if len(recent) < MIN_SAMPLES:
            return 0.0
        wr = sum(recent) / len(recent)
        if wr > NEUTRAL_WR:
            # Winning → lower threshold proportionally (max SCORE_LOWER_MAX)
            ratio = (wr - NEUTRAL_WR) / (1.0 - NEUTRAL_WR)
            return SCORE_LOWER_MAX * ratio
        # Losing → raise threshold proportionally (max SCORE_RAISE_MAX)
        ratio = (NEUTRAL_WR - wr) / NEUTRAL_WR
        return SCORE_RAISE_MAX * ratio

    # -- stats for dashboard ------------------------------------------------

    def get_stats(self) -> dict[str, float | int | str]:
        total_samples = sum(self._total.values())
        total_wins = sum(self._wins.values())
        wr = total_wins / total_samples if total_samples else 0.0
        recent_wr = self._overall_recent_wr()
        drift = self._detect_drift()
        return {
            "samples": total_samples,
            "accuracy": round(wr * 100, 1),
            "recent_accuracy": round(recent_wr * 100, 1),
            "drift": drift,
        }

    # -- internal -----------------------------------------------------------

    def _overall_recent_wr(self) -> float:
        all_recent: list[bool] = []
        for v in self._recent.values():
            all_recent.extend(v)
        if not all_recent:
            return 0.0
        return sum(all_recent) / len(all_recent)

    def _detect_drift(self) -> str:
        total = sum(self._total.values())
        if total < MIN_SAMPLES:
            return "Insufficient"
        overall = sum(self._wins.values()) / total
        recent = self._overall_recent_wr()
        if abs(recent - overall) > DRIFT_THRESHOLD:
            return "Drifting"
        return "Stable"
