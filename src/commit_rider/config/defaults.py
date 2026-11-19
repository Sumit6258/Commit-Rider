"""Default values, hard limits and named presets.

This module is data only: nothing here imports the rendering or animation code.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THEME = "midnight"
DEFAULT_BIKE = "bmx"
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 360
DEFAULT_FPS = 18
DEFAULT_DURATION = 8.0
DEFAULT_DAYS = 365
DEFAULT_MAX_SIZE_MB = 8.0

# Hard limits protect CI runners from accidental (or hostile) resource use.
MIN_WIDTH, MAX_WIDTH = 320, 2400
MIN_HEIGHT, MAX_HEIGHT = 96, 900
MIN_FPS, MAX_FPS = 5, 30
MIN_DURATION, MAX_DURATION = 2.0, 30.0
MIN_DAYS, MAX_DAYS = 7, 1100
MAX_FRAMES = 450
# width * height * frames, a proxy for the total rendering work.
MAX_RENDER_WORK = 600_000_000
# The animation is authored for a 360-unit-high canvas; everything scales from that.
DESIGN_HEIGHT = 360.0

BIKES = ("bmx",)
SCALING_METHODS = ("log", "sqrt", "linear", "rank")


@dataclass(frozen=True)
class RideMode:
    speed: float
    stunt_intensity: float
    description: str


RIDE_MODES: dict[str, RideMode] = {
    "normal": RideMode(1.0, 0.35, "Balanced ride: natural jumps, one wheelie."),
    "speed": RideMode(1.3, 0.25, "Faster and flatter: the track scrolls by quickly."),
    "stunt": RideMode(1.0, 0.95, "More air: bigger jumps, wheelies and the odd backflip."),
    "relaxed": RideMode(0.8, 0.10, "Slow cruise with very few jumps."),
}


@dataclass(frozen=True)
class TerrainMode:
    amplitude: float
    sigma: float
    gamma: float
    quantize: bool
    skew: float
    description: str


TERRAIN_MODES: dict[str, TerrainMode] = {
    "natural": TerrainMode(1.0, 1.0, 1.0, False, 0.0, "Natural hills (default)."),
    "rolling": TerrainMode(0.7, 1.7, 0.9, False, 0.0, "Smooth rolling terrain."),
    "ramps": TerrainMode(1.0, 0.8, 1.0, False, 2.2, "Gradual run-ups with abrupt lips."),
    "mountain": TerrainMode(1.35, 0.9, 1.35, False, 0.0, "Tall, peaky mountain trail."),
    "arcade": TerrainMode(1.0, 0.7, 1.0, True, 0.0, "Stepped plateaus, one per activity level."),
}


@dataclass(frozen=True)
class QualityPreset:
    supersample: int
    colors: int
    tolerance: int
    description: str


QUALITY_PRESETS: dict[str, QualityPreset] = {
    "draft": QualityPreset(1, 128, 4, "Fast and jagged: for iteration only."),
    "standard": QualityPreset(2, 255, 0, "Anti-aliased, 255 colours (default)."),
    "high": QualityPreset(3, 255, 0, "3x supersampling: slowest, smoothest edges."),
}
