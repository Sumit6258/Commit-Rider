"""Themes: pure data. Adding a theme never touches the animation or drawing code.

A theme is a frozen dataclass of colours and a few scenery switches. Built-in themes live
in ``THEMES``; custom ones can be registered at runtime with :func:`register_theme`
(the CLI exposes this as ``--theme-file``) and users can override individual colours
through ``Settings`` (``bike_color``, ``rider_color``, ``terrain_color``,
``background_color``).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from commit_rider.errors import ConfigError
from commit_rider.rendering.colors import darken, lighten, luminance, mix, rgb, to_hex


@dataclass(frozen=True)
class LayerSpec:
    kind: str  # "mountains" | "hills"
    color: str
    parallax: float  # fraction of the rider's travel
    base: float  # ridge baseline as a fraction of the view height (0 = top)
    amplitude: float  # ridge height in world units
    seed: int = 0
    snow: bool = False
    rim: str | None = None


@dataclass(frozen=True)
class Theme:
    name: str
    description: str = ""
    # ---- sky ----
    sky: tuple[tuple[float, str], ...] = ((0.0, "#9fd0ff"), (1.0, "#e8f4ff"))
    celestial: str = "none"  # "sun" | "moon" | "none"
    celestial_pos: tuple[float, float] = (0.8, 0.2)
    celestial_radius: float = 24.0
    celestial_color: str = "#fff4c2"
    celestial_glow: str = "#fff4c2"
    sun_stripes: bool = False
    stars: int = 0
    star_color: str = "#ffffff"
    clouds: int = 0
    cloud_color: str = "#ffffff"
    cloud_alpha: float = 0.85
    layers: tuple[LayerSpec, ...] = ()
    haze: str | None = None
    haze_alpha: float = 0.3
    falling_snow: bool = False
    # ---- terrain ----
    terrain_top: str = "#7a5c3a"
    terrain_bottom: str = "#3a2a1b"
    terrain_edge: str = "#7ed957"
    trail: tuple[str, str, str, str, str] = ("#8d7a52", "#9ccc5a", "#6fbf3c", "#3fa526", "#1f7d1d")
    strata: str | None = None
    strata_alpha: float = 0.15
    decor: str = "grass"  # "grass" | "snow" | "neon" | "none"
    decor_color: str = "#4fb82f"
    trees: str | None = None  # "pine" | None
    tree_color: str = "#2e6a4c"
    tree_snow: bool = False
    tree_density: float = 0.6
    glow: bool = False
    ink: str = "#1b1f2a"
    # ---- rider ----
    jersey: str = "#e63946"
    helmet: str = "#ffffff"
    skin: str = "#f0c4a0"
    shorts: str = "#25303b"
    shoes: str = "#f4f4f4"
    glove: str = "#25303b"
    # ---- bike ----
    frame: str = "#1d5fa8"
    fork: str = "#d0d7de"
    rim: str = "#c9d1d9"
    tire: str = "#1c1f23"
    spoke: str = "#9aa5b1"
    saddle: str = "#1c1f23"
    chain: str = "#59636e"
    # ---- misc ----
    dust: str = "#c8b28a"
    overlay_bg: str = "#ffffff"
    overlay_text: str = "#1f2933"
    overlay_accent: str = "#2f7cf6"
    overlay_alpha: float = 0.78
    extras: Mapping[str, Any] = field(default_factory=dict)

    # ----- derived / customised copies ---------------------------------------------
    def with_overrides(
        self,
        bike_color: str | None = None,
        rider_color: str | None = None,
        terrain_color: str | None = None,
        background_color: str | None = None,
    ) -> Theme:
        changes: dict[str, Any] = {}
        if bike_color:
            changes["frame"] = bike_color
        if rider_color:
            changes["jersey"] = rider_color
        if terrain_color:
            top = terrain_color
            changes.update(
                terrain_top=top,
                terrain_bottom=to_hex(darken(top, 0.6)),
                terrain_edge=to_hex(lighten(top, 0.45)),
                trail=(
                    to_hex(darken(top, 0.25)),
                    to_hex(mix(top, "#ffffff", 0.15)),
                    to_hex(mix(top, "#ffffff", 0.35)),
                    to_hex(mix(top, "#ffffff", 0.55)),
                    to_hex(mix(top, "#ffffff", 0.78)),
                ),
                decor_color=to_hex(darken(top, 0.1)),
            )
        if background_color:
            dark = luminance(background_color) < 0.45
            top = mix(background_color, "#ffffff" if dark else "#000000", 0.07)
            changes.update(
                sky=((0.0, to_hex(top)), (1.0, background_color)),
                haze=None,
                overlay_bg="#000000" if dark else "#ffffff",
                overlay_text="#f4f6fb" if dark else "#1f2933",
                overlay_alpha=0.55 if dark else 0.78,
            )
        return dataclasses.replace(self, **changes) if changes else self


def _l(kind: str, color: str, parallax: float, base: float, amp: float, seed: int, **kw: Any) -> LayerSpec:
    return LayerSpec(kind, color, parallax, base, amp, seed, **kw)


THEMES: dict[str, Theme] = {}


def _add(theme: Theme) -> None:
    THEMES[theme.name] = theme


_add(
    Theme(
        name="midnight",
        description="Deep navy night sky, a pale moon and glowing mint trails.",
        sky=((0.0, "#050816"), (0.45, "#10163f"), (0.8, "#27256b"), (1.0, "#4a3a8f")),
        celestial="moon", celestial_pos=(0.80, 0.20), celestial_radius=22,
        celestial_color="#f3f1d9", celestial_glow="#7c8cff",
        stars=70, star_color="#cfd8ff", clouds=3, cloud_color="#6d78c9", cloud_alpha=0.16,
        layers=(
            _l("mountains", "#1b2260", 0.26, 0.60, 78, 1, rim="#3b4aa8"),
            _l("mountains", "#141a4d", 0.42, 0.68, 58, 2, rim="#2f3c96"),
            _l("hills", "#0d1238", 0.62, 0.77, 36, 3),
        ),
        haze="#4a3a8f", haze_alpha=0.28,
        terrain_top="#4b3aa6", terrain_bottom="#0f1442", terrain_edge="#9ffbe6",
        trail=("#3b4390", "#12806f", "#19a982", "#2fd18f", "#8bffc3"),
        strata="#8b7bff", strata_alpha=0.10, decor="grass", decor_color="#1fa886",
        trees="pine", tree_color="#0a0f33", tree_density=0.55, ink="#0a0d24",
        jersey="#ff8a3d", helmet="#ffd166", skin="#f1c9a5", shorts="#1c2150", shoes="#f1f3ff",
        glove="#1c2150", frame="#38e1ff", fork="#c9d3ff", rim="#aeb9ff", tire="#0a0c1e",
        spoke="#8f9bdc", saddle="#0f1230", chain="#6f7ac0", dust="#8f98e0",
        overlay_bg="#0b1030", overlay_text="#e8ecff", overlay_accent="#5ef2d0", overlay_alpha=0.66,
    )
)

_add(
    Theme(
        name="forest",
        description="Sunny day, pine woods and earthy trails.",
        sky=((0.0, "#7cc4ff"), (0.55, "#bfe6ff"), (1.0, "#eaf8df")),
        celestial="sun", celestial_pos=(0.82, 0.20), celestial_radius=26,
        celestial_color="#fff3b0", celestial_glow="#fff9d6",
        clouds=4, cloud_color="#ffffff", cloud_alpha=0.88,
        layers=(
            _l("mountains", "#9fc5b8", 0.26, 0.60, 80, 11),
            _l("mountains", "#6fa58b", 0.42, 0.68, 60, 12),
            _l("hills", "#477f63", 0.62, 0.77, 38, 13),
        ),
        haze="#eaf8df", haze_alpha=0.35,
        terrain_top="#8a6a3f", terrain_bottom="#3e2c1d", terrain_edge="#9be56d",
        trail=("#8d7a52", "#9ccc5a", "#6fbf3c", "#3fa526", "#1f7d1d"),
        strata="#2b1c10", strata_alpha=0.18, decor="grass", decor_color="#4fb82f",
        trees="pine", tree_color="#2e6a4c", tree_density=0.8, ink="#1d2a1f",
        jersey="#e63946", helmet="#ffffff", skin="#e8b88f", shorts="#25303b",
        frame="#1d5fa8", dust="#c8b28a",
        overlay_bg="#ffffff", overlay_text="#1f2d1f", overlay_accent="#2f8f2a",
    )
)

_add(
    Theme(
        name="sunset",
        description="Purple-to-orange sky, a low sun and warm, glowing terrain.",
        sky=((0.0, "#2b0f5c"), (0.35, "#7b2a8f"), (0.65, "#e8506f"), (0.88, "#ff9a62"), (1.0, "#ffd27a")),
        celestial="sun", celestial_pos=(0.72, 0.56), celestial_radius=42,
        celestial_color="#fff0b8", celestial_glow="#ff8a5c",
        stars=24, star_color="#ffe9ff", clouds=3, cloud_color="#ff9fb0", cloud_alpha=0.32,
        layers=(
            _l("mountains", "#6a2a7e", 0.26, 0.62, 66, 21),
            _l("mountains", "#4a1d6b", 0.42, 0.69, 52, 22),
            _l("hills", "#2f1352", 0.62, 0.77, 36, 23),
        ),
        terrain_top="#8a3a74", terrain_bottom="#220f3f", terrain_edge="#ffc27a",
        trail=("#5a2a66", "#b3457a", "#e8606d", "#ff8a5c", "#ffd166"),
        strata="#ffb37a", strata_alpha=0.10, decor="grass", decor_color="#ff9d5c",
        trees="pine", tree_color="#240d41", tree_density=0.55, ink="#1b0b33",
        jersey="#19d3c5", helmet="#ffffff", skin="#f0c4a0", shorts="#1d1040", shoes="#ffffff",
        glove="#1d1040", frame="#ffe08a", fork="#f3d9ff", rim="#ffe9c7", tire="#150a2b",
        spoke="#e9b8d6", saddle="#150a2b", chain="#b27aa8", dust="#e8a8b8",
        overlay_bg="#1d0b3a", overlay_text="#fff1e0", overlay_accent="#ffc27a", overlay_alpha=0.62,
    )
)

_add(
    Theme(
        name="neon",
        description="Synthwave night: striped sun, neon rims and a glowing trail.",
        sky=((0.0, "#06020f"), (0.5, "#14052e"), (0.85, "#3a0a58"), (1.0, "#6b0f6b")),
        celestial="sun", celestial_pos=(0.50, 0.40), celestial_radius=46,
        celestial_color="#ffd34d", celestial_glow="#ff2e97", sun_stripes=True,
        stars=40, star_color="#ff9be6",
        layers=(
            _l("mountains", "#1a0a3d", 0.26, 0.63, 62, 31, rim="#b100ff"),
            _l("mountains", "#120730", 0.42, 0.70, 50, 32, rim="#ff2e97"),
            _l("hills", "#0b0420", 0.62, 0.78, 32, 33),
        ),
        terrain_top="#1a0a40", terrain_bottom="#07021a", terrain_edge="#00f0ff",
        trail=("#2a1458", "#6a1b9a", "#c2188f", "#ff2e97", "#00f0ff"),
        strata="#ff2e97", strata_alpha=0.22, decor="neon", decor_color="#00f0ff",
        glow=True, ink="#05010d",
        jersey="#fcee0c", helmet="#ff2e97", skin="#f3c6a5", shorts="#120730", shoes="#00f0ff",
        glove="#120730", frame="#00f0ff", fork="#ff2e97", rim="#7df9ff", tire="#05010d",
        spoke="#5fd9e6", saddle="#120730", chain="#b100ff", dust="#ff7be0",
        overlay_bg="#0b0420", overlay_text="#e9faff", overlay_accent="#00f0ff", overlay_alpha=0.66,
    )
)

_add(
    Theme(
        name="snow",
        description="Winter morning: snowy peaks, falling flakes and icy blue trails.",
        sky=((0.0, "#9fcdf2"), (0.5, "#cfe7fa"), (1.0, "#f6fbff")),
        celestial="sun", celestial_pos=(0.20, 0.22), celestial_radius=22,
        celestial_color="#ffffff", celestial_glow="#fff7d6",
        clouds=4, cloud_color="#ffffff", cloud_alpha=0.92,
        layers=(
            _l("mountains", "#c3d8ee", 0.26, 0.60, 86, 41, snow=True),
            _l("mountains", "#a5c1de", 0.42, 0.67, 64, 42, snow=True),
            _l("hills", "#e9f3fb", 0.62, 0.76, 32, 43),
        ),
        haze="#f6fbff", haze_alpha=0.4, falling_snow=True,
        terrain_top="#ffffff", terrain_bottom="#b5d0ea", terrain_edge="#7fa8cf",
        trail=("#e6f0f9", "#bcdcf5", "#86bdee", "#4d97dd", "#1e6bc1"),
        strata="#7fa8cf", strata_alpha=0.18, decor="snow", decor_color="#ffffff",
        trees="pine", tree_color="#4a6f8c", tree_snow=True, tree_density=0.65, ink="#1d3557",
        jersey="#e63946", helmet="#ffd60a", skin="#f2c7a5", shorts="#1d3557", shoes="#ffffff",
        glove="#1d3557", frame="#1d3557", fork="#8aa3bd", rim="#9fb4c9", tire="#1b2430",
        spoke="#8195ab", saddle="#1b2430", chain="#64788d", dust="#ffffff",
        overlay_bg="#ffffff", overlay_text="#1d3557", overlay_accent="#1e6bc1",
    )
)

_add(
    Theme(
        name="minimal",
        description="Clean light background, GitHub-green trail, understated artwork.",
        sky=((0.0, "#fbfbfc"), (1.0, "#f1f2f5")),
        layers=(_l("hills", "#eceef2", 0.62, 0.70, 30, 51),),
        terrain_top="#e3e6ec", terrain_bottom="#cdd2db", terrain_edge="#1f2328",
        trail=("#d0d7de", "#9be9a8", "#40c463", "#30a14e", "#216e39"),
        decor="none", ink="#1f2328",
        jersey="#2b3138", helmet="#2da44e", skin="#d9b99b", shorts="#1f2328", shoes="#ffffff",
        glove="#1f2328", frame="#1f2328", fork="#57606a", rim="#57606a", tire="#1f2328",
        spoke="#8c959f", saddle="#1f2328", chain="#57606a", dust="#c9ced8",
        overlay_bg="#ffffff", overlay_text="#1f2328", overlay_accent="#2da44e", overlay_alpha=0.85,
    )
)

_add(
    Theme(
        name="monochrome",
        description="Black, white and grey.",
        sky=((0.0, "#0a0a0a"), (1.0, "#2a2a2a")),
        celestial="moon", celestial_pos=(0.80, 0.20), celestial_radius=20,
        celestial_color="#f2f2f2", celestial_glow="#8a8a8a", stars=40, star_color="#d9d9d9",
        layers=(
            _l("mountains", "#1c1c1c", 0.26, 0.60, 76, 61, rim="#444444"),
            _l("mountains", "#151515", 0.42, 0.68, 56, 62, rim="#3a3a3a"),
            _l("hills", "#0f0f0f", 0.62, 0.77, 34, 63),
        ),
        terrain_top="#3d3d3d", terrain_bottom="#121212", terrain_edge="#f0f0f0",
        trail=("#2e2e2e", "#585858", "#858585", "#b8b8b8", "#ffffff"),
        decor="grass", decor_color="#9a9a9a", trees="pine", tree_color="#0c0c0c",
        tree_density=0.5, ink="#050505",
        jersey="#f2f2f2", helmet="#bdbdbd", skin="#cfcfcf", shorts="#3a3a3a", shoes="#ffffff",
        glove="#3a3a3a", frame="#ffffff", fork="#bdbdbd", rim="#d9d9d9", tire="#0a0a0a",
        spoke="#8c8c8c", saddle="#0a0a0a", chain="#7a7a7a", dust="#9a9a9a",
        overlay_bg="#0a0a0a", overlay_text="#f2f2f2", overlay_accent="#ffffff", overlay_alpha=0.66,
    )
)


def theme_names() -> tuple[str, ...]:
    return tuple(THEMES)


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name]
    except KeyError:
        raise ConfigError(f"Unknown theme {name!r}; available: {', '.join(THEMES)}") from None


def theme_from_mapping(data: Mapping[str, Any], base: str = "midnight") -> Theme:
    """Build a theme from a plain mapping (e.g. parsed JSON), inheriting from ``base``."""
    if "name" not in data:
        raise ConfigError("A custom theme needs a 'name'")
    known = {f.name for f in dataclasses.fields(Theme)}
    unknown = sorted(set(data) - known - {"base"})
    if unknown:
        raise ConfigError(f"Unknown theme field(s): {', '.join(unknown)}")
    values = {k: v for k, v in data.items() if k != "base"}
    if "layers" in values:
        values["layers"] = tuple(
            _layer_from_mapping(x) if isinstance(x, Mapping) else x for x in values["layers"]
        )
    if "sky" in values:
        values["sky"] = tuple((float(p), str(c)) for p, c in values["sky"])
    if "trail" in values:
        values["trail"] = tuple(values["trail"])
    if "celestial_pos" in values:
        values["celestial_pos"] = tuple(values["celestial_pos"])
    try:
        theme = dataclasses.replace(get_theme(str(data.get("base", base))), **values)
        _validate_theme(theme)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"Invalid custom theme: {exc}") from None
    return theme


_NUMERIC_FIELDS = (
    "celestial_radius", "stars", "clouds", "cloud_alpha", "haze_alpha", "strata_alpha",
    "tree_density", "overlay_alpha",
)


def _validate_theme(theme: Theme) -> None:
    """Raise ValueError/TypeError if any colour or number in the theme is unusable."""
    for f in dataclasses.fields(Theme):
        if isinstance(f.default, str) and f.default.startswith("#"):  # a colour field
            rgb(getattr(theme, f.name))
    for optional in (theme.haze, theme.strata):
        if optional:
            rgb(optional)
    for _, color in theme.sky:
        rgb(color)
    if len(theme.sky) < 2:
        raise ValueError("'sky' needs at least two gradient stops")
    if len(theme.trail) != 5:
        raise ValueError("'trail' needs exactly five colours")
    for color in theme.trail:
        rgb(color)
    for layer in theme.layers:
        rgb(layer.color)
        if layer.rim:
            rgb(layer.rim)
        if layer.kind not in ("mountains", "hills") or not 0 < layer.parallax <= 1:
            raise ValueError("a layer needs kind 'mountains' or 'hills' and parallax in (0, 1]")
    for name in _NUMERIC_FIELDS:
        value = getattr(theme, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{name}' must be a number")
    if theme.celestial not in ("sun", "moon", "none") or theme.decor not in ("grass", "snow", "neon", "none"):
        raise ValueError("unknown 'celestial' or 'decor' value")
    if theme.trees not in (None, "pine"):
        raise ValueError("'trees' must be null or 'pine'")


def _layer_from_mapping(data: Mapping[str, Any]) -> LayerSpec:
    try:
        return LayerSpec(**dict(data))
    except TypeError as exc:
        raise ConfigError(f"Invalid theme layer: {exc}") from None


def register_theme(theme: Theme) -> None:
    THEMES[theme.name] = theme


def load_theme_file(path: str | Path) -> Theme:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read theme file {path}: {exc}") from None
    if not isinstance(data, Mapping):
        raise ConfigError("A theme file must contain a JSON object")
    theme = theme_from_mapping(data)
    register_theme(theme)
    return theme
