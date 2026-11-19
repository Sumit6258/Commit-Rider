"""Map daily contribution counts to normalised terrain levels.

Levels are dimensionless: 0 is the valley floor, 1.0 is a "reference" day and values
up to ``soft_cap`` (default 1.35) are reserved for exceptional days.

Design notes (see docs/architecture.md for the numbers behind them):

* The reference count is a *percentile of the active days* (default p90), not the maximum,
  so a single 400-commit day cannot flatten every other hill.
* Counts above the reference are compressed with a tanh shoulder instead of being
  clipped, so exceptional days still stand out as peaks or ramps.
* ``log`` (default) keeps small days visible; ``sqrt`` and ``linear`` are available;
  ``rank`` ignores magnitude entirely and uses the day's percentile among active days.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

from commit_rider.config.defaults import SCALING_METHODS


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (``q`` in 0..1) of an ascending sequence."""
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be within 0..1")
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    frac = position - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def reference_count(counts: Sequence[int], q: float = 0.9) -> float:
    """Percentile ``q`` of the non-zero counts (0.0 when there are none)."""
    active = sorted(c for c in counts if c > 0)
    return percentile(active, q) if active else 0.0


def _transform(count: float, method: str) -> float:
    if method == "log":
        return math.log1p(count)
    if method == "sqrt":
        return math.sqrt(count)
    return float(count)


def scale_counts(
    counts: Sequence[int],
    method: str = "log",
    reference_q: float = 0.9,
    soft_cap: float = 1.35,
) -> list[float]:
    """Return one level per day; see the module docstring."""
    if method not in SCALING_METHODS:
        raise ValueError(f"unknown scaling method {method!r}; choose from {SCALING_METHODS}")
    if soft_cap <= 1.0:
        raise ValueError("soft_cap must be greater than 1")
    if any(c < 0 for c in counts):
        raise ValueError("contribution counts cannot be negative")
    if not counts:
        return []

    active = [c for c in counts if c > 0]
    if not active:
        return [0.0] * len(counts)  # no contributions at all: a flat valley
    if len(active) == len(counts) and min(active) == max(active):
        return [0.5] * len(counts)  # identical every day: a flat, mid-height plain

    if method == "rank":
        ordered = sorted(active)
        levels = []
        for c in counts:
            if c == 0:
                levels.append(0.0)
                continue
            mid_rank = (bisect_left(ordered, c) + bisect_right(ordered, c)) / 2
            levels.append(0.15 + 0.85 * mid_rank / len(ordered))
        return levels

    reference = _transform(reference_count(counts, reference_q), method)
    shoulder = soft_cap - 1.0
    levels = []
    for c in counts:
        u = _transform(c, method) / reference
        if u > 1.0:
            u = 1.0 + shoulder * math.tanh((u - 1.0) / shoulder)
        levels.append(u)
    return levels


def activity_levels(counts: Sequence[int]) -> tuple[int, ...]:
    """GitHub-style 0..4 intensity per day, from quartiles of the active days."""
    active = sorted(c for c in counts if c > 0)
    if not active:
        return (0,) * len(counts)
    q1, q2, q3 = (percentile(active, q) for q in (0.25, 0.5, 0.75))
    out = []
    for c in counts:
        if c == 0:
            out.append(0)
        elif c <= q1:
            out.append(1)
        elif c <= q2:
            out.append(2)
        elif c <= q3:
            out.append(3)
        else:
            out.append(4)
    return tuple(out)
