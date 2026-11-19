"""Pre-render the terrain (trail, strata, decorations, trees) as one wide strip.

The strip covers exactly one lap in world x, so it can be scrolled with
``paste_periodic`` and joins itself seamlessly. It is drawn once; per frame only a crop
is pasted.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from commit_rider.rendering.colors import darken, lighten, mix, rgb
from commit_rider.rendering.drawing import Painter, vertical_gradient
from commit_rider.rendering.themes import Theme
from commit_rider.terrain.geometry import Terrain

TRAIL_THICKNESS = 7.0
TREE_MAX = 78.0


class TerrainStrip:
    """``image`` plus the mapping from world coordinates to strip pixels."""

    def __init__(self, image: Image.Image, y_top: float, ppu: float, period: float) -> None:
        self.image = image
        self.y_top = y_top
        self.ppu = ppu
        self.period = period
        self.kx = image.width / period

    def row_of(self, world_y: float) -> float:
        return (self.y_top - world_y) * self.ppu


def _pine(painter: Painter, base: tuple[float, float], height: float, color, snow: bool, snow_color) -> None:
    x, y = base
    trunk_h = height * 0.14
    painter.draw.rectangle(
        [x - height * 0.035 * painter.scale, y - trunk_h * painter.scale, x + height * 0.035 * painter.scale, y + 6 * painter.scale],
        fill=darken(color, 0.25),
    )
    tiers = 3
    for i in range(tiers):
        base_y = y - height * (0.10 + 0.25 * i) * painter.scale
        top_y = base_y - height * 0.44 * painter.scale
        half = height * (0.30 - 0.055 * i) * painter.scale
        painter.draw.polygon([(x - half, base_y), (x + half, base_y), (x, top_y)], fill=color)
        if snow:
            cap = 0.55
            painter.draw.polygon(
                [(x - half * cap, base_y - (base_y - top_y) * (1 - cap)), (x + half * cap, base_y - (base_y - top_y) * (1 - cap)), (x, top_y)],
                fill=snow_color,
            )


def build_terrain_strip(
    terrain: Terrain,
    theme: Theme,
    ppu: float,
    cam_y_min: float,
    cam_y_max: float,
    view_height_wu: float,
    anchor_y: float,
    seed: int = 0,
) -> TerrainStrip:
    period = terrain.period
    width = max(16, round(period * ppu))
    y_top = max(terrain.max_height + TREE_MAX + 16.0, cam_y_max + anchor_y * view_height_wu + 10.0)
    y_bottom = min(terrain.min_height - 10.0, cam_y_min - (1.0 - anchor_y) * view_height_wu - 20.0)
    height = max(16, round((y_top - y_bottom) * ppu))
    strip = TerrainStrip(Image.new("RGBA", (width, height), (0, 0, 0, 0)), y_top, ppu, period)
    kx = strip.kx

    def px(x: float, h: float) -> tuple[float, float]:
        return (x * kx, strip.row_of(h))

    painter = Painter(strip.image, ppu, lambda x, y: (x, y))  # mapper takes pixel coords
    rng = random.Random(seed * 977 + 31)

    surface = [px(i / kx, terrain.height(i / kx)) for i in range(width)]

    # ---- trees (behind the trail; their trunks are buried by the body fill) -----------
    if theme.trees == "pine":
        x = rng.uniform(10, 60)
        tree_color = rgb(theme.tree_color)
        while x < period:
            if rng.random() < theme.tree_density:
                h = rng.uniform(40, 72)
                shade = mix(tree_color, lighten(tree_color, 0.25), rng.random() * 0.5)
                _pine(painter, px(x, terrain.height(x) - 1.0), h, shade, theme.tree_snow, (244, 249, 255))
            x += rng.uniform(34, 105)

    # ---- body: gradient clipped by the surface polygon ---------------------------------
    mask = Image.new("L", strip.image.size, 0)
    ImageDraw.Draw(mask).polygon(surface + [(width - 1, height), (0, height)], fill=255)
    gradient = vertical_gradient(
        strip.image.size,
        [(0.0, theme.terrain_top), (0.45, theme.terrain_top), (1.0, theme.terrain_bottom)],
    )
    strip.image.paste(gradient, (0, 0), mask)

    # ---- strata: faint parallel contours below the surface -----------------------------
    if theme.strata:
        overlay = Image.new("RGBA", strip.image.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        color = rgb(theme.strata)
        for k in range(1, 8):
            alpha = int(255 * theme.strata_alpha * (1.0 - k / 9.0))
            offset = k * 15.0 * ppu
            od.line([(x, y + offset) for x, y in surface[::3]], fill=color + (alpha,), width=max(1, round(1.2 * ppu)), joint="curve")
        clipped = Image.new("RGBA", strip.image.size, (0, 0, 0, 0))
        clipped.paste(overlay, (0, 0), mask)
        strip.image.alpha_composite(clipped)

    # ---- trail band: one colour per day, coloured by activity level ------------------
    thick = TRAIL_THICKNESS * ppu
    levels = list(terrain.day_levels) + [0] * terrain.bridge_days
    trail = [rgb(c) for c in theme.trail]
    band = ImageDraw.Draw(strip.image)
    for d, level in enumerate(levels):
        x0 = max(0, int(d * terrain.day_width * kx) - 1)
        x1 = min(width - 1, int((d + 1) * terrain.day_width * kx) + 1)
        if x1 <= x0:
            continue
        top = surface[x0 : x1 + 1]
        poly = top + [(x, y + thick) for x, y in reversed(top)]
        band.polygon(poly, fill=trail[level])

    # ---- surface decoration -------------------------------------------------------------
    edge = rgb(theme.terrain_edge)
    edge_w = max(1.0, (2.6 if theme.decor == "none" else 2.0) * ppu)
    if theme.decor == "snow":
        cap = Image.new("RGBA", strip.image.size, (0, 0, 0, 0))
        cd = ImageDraw.Draw(cap)
        top = [(x, y - (2.2 + 1.3 * math.sin(x / (9 * ppu)) + 0.8 * math.sin(x / (3.7 * ppu))) * ppu) for x, y in surface]
        cd.polygon(top + list(reversed(surface)), fill=(250, 253, 255, 255))
        strip.image.alpha_composite(cap)
    if theme.decor == "neon" or theme.glow:
        glow = Image.new("RGBA", strip.image.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).line(surface[::2], fill=edge + (255,), width=max(2, round(4.5 * ppu)), joint="curve")
        glow = glow.filter(ImageFilter.GaussianBlur(radius=5.0 * ppu))
        glow.putalpha(glow.getchannel("A").point(lambda a: min(255, int(a * 1.6))))
        under = Image.new("RGBA", strip.image.size, (0, 0, 0, 0))
        under.alpha_composite(glow)
        under.alpha_composite(strip.image)
        strip.image.paste(under, (0, 0))
    ImageDraw.Draw(strip.image).line(surface[::2], fill=edge + (255,), width=round(edge_w), joint="curve")

    if theme.decor == "grass":
        blades = ImageDraw.Draw(strip.image)
        color = rgb(theme.decor_color)
        x = rng.uniform(2, 8)
        while x < period:
            i = min(width - 1, int(x * kx))
            sx, sy = surface[i]
            h = rng.uniform(2.4, 5.6) * ppu
            lean = rng.uniform(-1.8, 1.8) * ppu
            half = 1.5 * ppu
            blades.polygon([(sx - half, sy + 0.8 * ppu), (sx + half, sy + 0.8 * ppu), (sx + lean, sy - h)], fill=color)
            x += rng.uniform(6.0, 13.0)
    return strip
