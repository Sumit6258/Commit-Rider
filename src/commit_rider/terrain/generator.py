"""Contribution counts -> Terrain.

Pipeline: scale counts -> (optional mode shaping) -> close the loop with a bridge ->
Gaussian smoothing -> auto-contrast for sparse data -> periodic PCHIP -> micro relief -> rounding pass -> slope limit.
Everything is a pure function of its inputs: identical data and parameters give
identical geometry on every machine.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from commit_rider.config.defaults import DESIGN_HEIGHT, TERRAIN_MODES
from commit_rider.errors import ConfigError, DataError
from commit_rider.terrain.geometry import Terrain
from commit_rider.terrain.interpolation import (
    limit_rate,
    sample_periodic_pchip,
    smooth_circular,
    smoothstep,
)
from commit_rider.terrain.scaling import activity_levels, scale_counts


AUTO_CONTRAST_TARGET = 0.75
AUTO_CONTRAST_MAX_GAIN = 2.5


@dataclass(frozen=True)
class TerrainParams:
    day_width: float = 14.0
    base_height: float = 22.0
    amplitude: float = 112.0
    sigma_days: float = 1.2
    gamma: float = 1.0
    scaling: str = "log"
    reference_percentile: float = 0.9
    soft_cap: float = 1.35
    bridge_days: int = 16
    quantize: bool = False
    skew_days: float = 0.0
    micro_relief: float = 2.5
    max_slope: float = 1.0
    rounding: float = 5.0
    seed: int = 0

    def __post_init__(self) -> None:
        if not 4.0 <= self.day_width <= 80.0:
            raise ConfigError("day_width must be between 4 and 80 world units")
        if self.bridge_days < 4:
            raise ConfigError("bridge_days must be at least 4")
        if self.amplitude <= 0 or self.max_slope <= 0:
            raise ConfigError("amplitude and max_slope must be positive")


def params_from_settings(settings) -> TerrainParams:  # noqa: ANN001 (avoid import cycle)
    """Translate user-facing Settings into terrain parameters."""
    mode = TERRAIN_MODES[settings.terrain_mode]
    sigma = (1.0 + 1.6 * settings.smoothing) * mode.sigma
    return TerrainParams(
        day_width=min(40.0, max(6.0, 14.0 * settings.effective_speed)),
        amplitude=112.0 * settings.height_sensitivity * mode.amplitude,
        sigma_days=sigma,
        gamma=mode.gamma,
        scaling=settings.scaling,
        quantize=mode.quantize,
        skew_days=mode.skew,
        seed=settings.seed,
    )


def _build_loop(levels: Sequence[float], bridge_days: int) -> list[float]:
    """Append a bridge that eases from the last level down to a shallow valley and back
    up to the first level, so the sequence is smooth when treated as a circle."""
    last, first = levels[-1], levels[0]
    valley = min(last, first, 0.10)
    out = list(levels)
    for i in range(bridge_days):
        t = (i + 1) / (bridge_days + 1)
        if t < 0.5:
            out.append(last + (valley - last) * smoothstep(t / 0.5))
        else:
            out.append(valley + (first - valley) * smoothstep((t - 0.5) / 0.5))
    return out


def _quantize(levels: Sequence[float]) -> list[float]:
    """Arcade mode: snap to five plateaus (quarter steps of the 0..1 range)."""
    return [min(1.35, round(min(level, 1.0) * 4) / 4 + (0.1 if level > 1.0 else 0.0)) for level in levels]


def _skew_forward(levels: Sequence[float], days: float) -> list[float]:
    """Ramps mode: each day also lifts the days *before* it (one-sided exponential),
    producing a gradual run-up and an abrupt drop right after the peak."""
    n = len(levels)
    reach = max(2, math.ceil(days * 3))
    weights = [math.exp(-k / days) for k in range(reach + 1)]
    out = []
    for i in range(n):
        best = levels[i]
        for k in range(1, reach + 1):
            if i + k < n:
                best = max(best, levels[i + k] * weights[k])
        out.append(best)
    return out


def _limit_slope(heights: list[float], dx: float, max_slope: float) -> list[float]:
    """Guarantee ``|dh/dx| <= max_slope``.

    Peaks are lowered by the lower cone envelope and valleys raised by the upper one;
    the average of the two is exactly ``max_slope``-Lipschitz and equals the input where
    the input already satisfies the limit. A light Gaussian pass then removes corners
    (convolution with a positive kernel cannot increase the maximum slope).
    """
    return smooth_circular(limit_rate(heights, max_slope * dx), 3.0 / dx)


def generate_terrain(counts: Sequence[int], params: TerrainParams | None = None) -> Terrain:
    params = params or TerrainParams()
    if not counts:
        raise DataError("Cannot generate terrain from an empty contribution list")
    if any((not isinstance(c, int)) or c < 0 for c in counts):
        raise DataError("Contribution counts must be non-negative integers")

    n_days = len(counts)
    levels = scale_counts(counts, params.scaling, params.reference_percentile, params.soft_cap)
    if params.quantize:
        levels = _quantize(levels)
    if params.skew_days > 0:
        levels = _skew_forward(levels, params.skew_days)

    loop = _build_loop(levels, params.bridge_days)
    loop = smooth_circular(loop, params.sigma_days)
    # Sparse accounts: smoothing spreads a lone busy day over several days and flattens it.
    # If the tallest hill ends up below 75% of the reference height, scale every level up by
    # the same factor (at most x2.5). Relative heights are untouched; dense data gets x1.
    peak = max(loop[:n_days])
    if 0.0 < peak < AUTO_CONTRAST_TARGET:
        gain = min(AUTO_CONTRAST_MAX_GAIN, AUTO_CONTRAST_TARGET / peak)
        loop = [v * gain for v in loop]
    control = [params.base_height + params.amplitude * (max(v, 0.0) ** params.gamma) for v in loop]

    sub = max(1, round(params.day_width))
    dx = params.day_width / sub
    period = len(control) * params.day_width
    heights = sample_periodic_pchip(control, sub)

    # Micro relief: two sine waves with a whole number of cycles per lap (so the loop
    # stays seamless) keep long zero-contribution stretches from being a dead-flat ruler.
    rng = random.Random(params.seed * 7919 + 17)
    cycles_a = max(2, round(period / 310.0))
    cycles_b = max(3, round(period / 157.0))
    phase_a, phase_b = rng.random() * math.tau, rng.random() * math.tau
    n = len(heights)
    for i in range(n):
        angle = math.tau * i / n
        heights[i] += params.micro_relief * math.sin(cycles_a * angle + phase_a)
        heights[i] += 0.55 * params.micro_relief * math.sin(cycles_b * angle + phase_b)

    heights = smooth_circular(heights, params.rounding / dx)
    heights = _limit_slope(heights, dx, params.max_slope)
    heights = [max(0.0, h) for h in heights]

    return Terrain(
        heights=heights,
        dx=dx,
        period=period,
        day_width=params.day_width,
        num_days=n_days,
        bridge_days=params.bridge_days,
        counts=tuple(counts),
        day_levels=activity_levels(counts),
    )


__all__ = ["DESIGN_HEIGHT", "TerrainParams", "generate_terrain", "params_from_settings"]
