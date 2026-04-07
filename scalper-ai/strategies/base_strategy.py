from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.signal_generator import ScoreComponents, Signal
    from data.cache import MarketSnapshot


# Maximum score cap per component
CAP_CVD = 0.25
CAP_OB = 0.20
CAP_VOLUME = 0.15
CAP_STRUCTURE = 0.15
CAP_REGIME = 0.15
CAP_ML = 0.10
MIN_SCORE = 0.50


class BaseStrategy(ABC):
    """Abstract base — every strategy implements compute_signal()."""

    @abstractmethod
    def compute_signal(
        self, snap: MarketSnapshot, ml_boost: float,
    ) -> Signal | None:
        """Return a Signal if conditions met, else None."""

    @staticmethod
    def score_components(comp: ScoreComponents) -> float:
        """Compute capped total score."""
        return comp.total()
