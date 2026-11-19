"""User-facing configuration: one validated, immutable object.

``Settings`` is the only thing the CLI, the GitHub Action and (in future) a web
configurator need to build. It can be created from a mapping (with string
coercion, so Action inputs work), serialised with :meth:`to_dict` and described
with :func:`option_schema`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from commit_rider.config import defaults as d
from commit_rider.errors import ConfigError

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}


def normalize_color(value: str) -> str:
    """Return ``#rrggbb`` for ``#rgb``/``#rrggbb`` input, or raise ValueError."""
    m = _HEX.match(value.strip())
    if not m:
        raise ValueError(f"{value!r} is not a hex colour such as #1f6feb")
    digits = m.group(1).lower()
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits


@dataclass(frozen=True)
class Settings:
    theme: str = d.DEFAULT_THEME
    bike: str = d.DEFAULT_BIKE
    width: int = d.DEFAULT_WIDTH
    height: int = d.DEFAULT_HEIGHT
    fps: int = d.DEFAULT_FPS
    duration: float = d.DEFAULT_DURATION
    ride_mode: str = "normal"
    terrain_mode: str = "natural"
    speed: float = 1.0
    height_sensitivity: float = 1.0
    smoothing: float = 0.5
    stunt_intensity: float | None = None
    particles: bool = True
    show_stats: bool = False
    quality: str = "standard"
    max_size_mb: float = d.DEFAULT_MAX_SIZE_MB
    seed: int = 0
    scaling: str = "log"
    bike_color: str | None = None
    rider_color: str | None = None
    terrain_color: str | None = None
    background_color: str | None = None

    def __post_init__(self) -> None:
        problems: list[str] = []

        def check(ok: bool, message: str) -> None:
            if not ok:
                problems.append(message)

        # Imported lazily: the theme registry lives in the rendering package.
        from commit_rider.rendering.themes import theme_names

        check(self.theme in theme_names(), f"theme must be one of {', '.join(theme_names())}")
        check(self.bike in d.BIKES, f"bike must be one of {', '.join(d.BIKES)}")
        check(
            isinstance(self.width, int) and d.MIN_WIDTH <= self.width <= d.MAX_WIDTH,
            f"width must be an integer between {d.MIN_WIDTH} and {d.MAX_WIDTH}",
        )
        check(
            isinstance(self.height, int) and d.MIN_HEIGHT <= self.height <= d.MAX_HEIGHT,
            f"height must be an integer between {d.MIN_HEIGHT} and {d.MAX_HEIGHT}",
        )
        check(
            isinstance(self.fps, int) and d.MIN_FPS <= self.fps <= d.MAX_FPS,
            f"fps must be an integer between {d.MIN_FPS} and {d.MAX_FPS}",
        )
        check(
            d.MIN_DURATION <= self.duration <= d.MAX_DURATION,
            f"duration must be between {d.MIN_DURATION:g} and {d.MAX_DURATION:g} seconds",
        )
        check(self.ride_mode in d.RIDE_MODES, f"ride_mode must be one of {list(d.RIDE_MODES)}")
        check(
            self.terrain_mode in d.TERRAIN_MODES,
            f"terrain_mode must be one of {list(d.TERRAIN_MODES)}",
        )
        check(0.4 <= self.speed <= 2.0, "speed must be between 0.4 and 2.0")
        check(0.3 <= self.height_sensitivity <= 2.0, "height_sensitivity must be 0.3 to 2.0")
        check(0.0 <= self.smoothing <= 1.0, "smoothing must be between 0 and 1")
        check(
            self.stunt_intensity is None or 0.0 <= self.stunt_intensity <= 1.0,
            "stunt_intensity must be between 0 and 1",
        )
        check(self.quality in d.QUALITY_PRESETS, f"quality must be one of {list(d.QUALITY_PRESETS)}")
        check(0.2 <= self.max_size_mb <= 100.0, "max_size_mb must be between 0.2 and 100")
        check(self.scaling in d.SCALING_METHODS, f"scaling must be one of {list(d.SCALING_METHODS)}")
        check(isinstance(self.seed, int), "seed must be an integer")
        for name in ("bike_color", "rider_color", "terrain_color", "background_color"):
            value = getattr(self, name)
            if value is None:
                continue
            try:
                object.__setattr__(self, name, normalize_color(value))
            except (ValueError, AttributeError) as exc:
                problems.append(f"{name}: {exc}")
        if not problems:
            frames = self.frames
            check(frames <= d.MAX_FRAMES, f"duration x fps = {frames} frames; the limit is {d.MAX_FRAMES}")
            work = self.width * self.height * frames
            check(
                work <= d.MAX_RENDER_WORK,
                "width x height x frames is too large for a CI runner; reduce size, fps or duration",
            )
        if problems:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))

    # ----- derived values -------------------------------------------------
    @property
    def frames(self) -> int:
        return max(2, round(self.duration * self.fps))

    @property
    def unit(self) -> float:
        """Output pixels per world unit (the scene is authored at 360 units high)."""
        return self.height / d.DESIGN_HEIGHT

    @property
    def view_width(self) -> float:
        """Width of the camera view in world units."""
        return self.width / self.unit

    @property
    def effective_speed(self) -> float:
        return d.RIDE_MODES[self.ride_mode].speed * self.speed

    @property
    def effective_stunts(self) -> float:
        if self.stunt_intensity is not None:
            return self.stunt_intensity
        return d.RIDE_MODES[self.ride_mode].stunt_intensity

    @property
    def quality_preset(self) -> d.QualityPreset:
        return d.QUALITY_PRESETS[self.quality]

    # ----- construction / serialisation ----------------------------------
    def with_changes(self, **changes: Any) -> Settings:
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Settings:
        """Build Settings from loosely typed input (CLI, JSON file, Action inputs)."""
        valid = {f.name for f in fields(cls)}
        values: dict[str, Any] = {}
        unknown: list[str] = []
        for raw_key, raw_value in data.items():
            key = str(raw_key).replace("-", "_")
            if key not in valid:
                unknown.append(str(raw_key))
                continue
            coerced = _COERCERS[key](key, raw_value)
            if coerced is not _UNSET:
                values[key] = coerced
        if unknown:
            raise ConfigError(
                f"Unknown setting(s): {', '.join(sorted(unknown))}. "
                f"Valid settings: {', '.join(sorted(valid))}"
            )
        return cls(**values)


# ----- coercion helpers -------------------------------------------------------
_UNSET = object()


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _int(name: str, value: Any) -> Any:
    if _blank(value):
        return _UNSET
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        return int(float(value)) if isinstance(value, str) and "." in value else int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer, got {value!r}") from None


def _float(name: str, value: Any) -> Any:
    if _blank(value):
        return _UNSET
    try:
        if isinstance(value, bool):
            raise ValueError
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a number, got {value!r}") from None


def _bool(name: str, value: Any) -> Any:
    if _blank(value):
        return _UNSET
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}")


def _str(name: str, value: Any) -> Any:
    if _blank(value):
        return _UNSET
    return str(value).strip().lower() if name in _LOWERCASE else str(value).strip()


_LOWERCASE = {"theme", "bike", "ride_mode", "terrain_mode", "quality", "scaling"}

_COERCERS: dict[str, Callable[[str, Any], Any]] = {
    "theme": _str,
    "bike": _str,
    "width": _int,
    "height": _int,
    "fps": _int,
    "duration": _float,
    "ride_mode": _str,
    "terrain_mode": _str,
    "speed": _float,
    "height_sensitivity": _float,
    "smoothing": _float,
    "stunt_intensity": _float,
    "particles": _bool,
    "show_stats": _bool,
    "quality": _str,
    "max_size_mb": _float,
    "seed": _int,
    "scaling": _str,
    "bike_color": _str,
    "rider_color": _str,
    "terrain_color": _str,
    "background_color": _str,
}


def option_schema() -> dict[str, dict[str, Any]]:
    """Machine-readable description of every option (docs, future web configurator)."""
    from commit_rider.rendering.themes import theme_names

    defaults = Settings()
    schema: dict[str, dict[str, Any]] = {
        "theme": {"type": "string", "enum": list(theme_names())},
        "bike": {"type": "string", "enum": list(d.BIKES)},
        "width": {"type": "integer", "minimum": d.MIN_WIDTH, "maximum": d.MAX_WIDTH},
        "height": {"type": "integer", "minimum": d.MIN_HEIGHT, "maximum": d.MAX_HEIGHT},
        "fps": {"type": "integer", "minimum": d.MIN_FPS, "maximum": d.MAX_FPS},
        "duration": {"type": "number", "minimum": d.MIN_DURATION, "maximum": d.MAX_DURATION},
        "ride_mode": {"type": "string", "enum": list(d.RIDE_MODES)},
        "terrain_mode": {"type": "string", "enum": list(d.TERRAIN_MODES)},
        "speed": {"type": "number", "minimum": 0.4, "maximum": 2.0},
        "height_sensitivity": {"type": "number", "minimum": 0.3, "maximum": 2.0},
        "smoothing": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "stunt_intensity": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
        "particles": {"type": "boolean"},
        "show_stats": {"type": "boolean"},
        "quality": {"type": "string", "enum": list(d.QUALITY_PRESETS)},
        "max_size_mb": {"type": "number", "minimum": 0.2, "maximum": 100},
        "seed": {"type": "integer"},
        "scaling": {"type": "string", "enum": list(d.SCALING_METHODS)},
        "bike_color": {"type": ["string", "null"], "pattern": "^#[0-9a-f]{6}$"},
        "rider_color": {"type": ["string", "null"], "pattern": "^#[0-9a-f]{6}$"},
        "terrain_color": {"type": ["string", "null"], "pattern": "^#[0-9a-f]{6}$"},
        "background_color": {"type": ["string", "null"], "pattern": "^#[0-9a-f]{6}$"},
    }
    for name, entry in schema.items():
        entry["default"] = getattr(defaults, name)
    return schema
