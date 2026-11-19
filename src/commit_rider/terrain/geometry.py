"""The Terrain object: a periodic height field with fast, deterministic queries."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Terrain:
    """A closed (periodic) trail.

    ``heights`` holds ``n`` samples spaced ``dx`` world units apart covering
    ``[0, period)``. Days ``0..num_days-1`` occupy the first ``num_days * day_width``
    units; the remaining ``bridge_days`` days are the closing transition that joins the
    end of the data back to its start so the ride can loop without a visible seam.
    """

    heights: list[float]
    dx: float
    period: float
    day_width: float
    num_days: int
    bridge_days: int
    counts: tuple[int, ...]
    day_levels: tuple[int, ...]
    slopes: list[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        n = len(self.heights)
        h = self.heights
        self.slopes = [(h[(i + 1) % n] - h[i - 1]) / (2.0 * self.dx) for i in range(n)]

    # ----- queries ---------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.heights)

    @property
    def min_height(self) -> float:
        return min(self.heights)

    @property
    def max_height(self) -> float:
        return max(self.heights)

    @property
    def data_length(self) -> float:
        return self.num_days * self.day_width

    def wrap(self, x: float) -> float:
        return x % self.period

    def _locate(self, x: float) -> tuple[int, float]:
        u = (x % self.period) / self.dx
        i = int(u)
        if i >= self.n:  # float edge case: x % period can round up to period
            i = 0
            u = 0.0
        return i, u - i

    def height(self, x: float) -> float:
        i, f = self._locate(x)
        return self.heights[i] * (1.0 - f) + self.heights[(i + 1) % self.n] * f

    def slope(self, x: float) -> float:
        i, f = self._locate(x)
        return self.slopes[i] * (1.0 - f) + self.slopes[(i + 1) % self.n] * f

    def angle(self, x: float) -> float:
        """Tangent angle in radians (positive = uphill in the direction of travel)."""
        return math.atan(self.slope(x))

    def day_index_at(self, x: float) -> int | None:
        """Index of the data day under ``x``, or ``None`` inside the closing bridge."""
        index = int((x % self.period) / self.day_width)
        return index if index < self.num_days else None
