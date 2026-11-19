"""Low-level drawing helpers built on Pillow.

Pillow rasterises without anti-aliasing and snaps coordinates to whole pixels, so every
layer is drawn at a higher resolution (supersampled) and reduced with a box filter. The
``Painter`` takes coordinates in any user space and maps them to pixels, so the same
drawing code serves the terrain strip, the scenery and the per-frame sprites.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PIL import Image, ImageDraw

from commit_rider.rendering.colors import Color, rgb

Point = tuple[float, float]


def sample_stops(stops: Sequence[tuple[float, str | Color]], t: float) -> Color:
    t = min(1.0, max(0.0, t))
    prev_pos, prev_col = stops[0][0], rgb(stops[0][1])
    if t <= prev_pos:
        return prev_col
    for pos, col in stops[1:]:
        col = rgb(col)
        if t <= pos:
            span = max(pos - prev_pos, 1e-9)
            f = (t - prev_pos) / span
            return tuple(round(prev_col[i] + (col[i] - prev_col[i]) * f) for i in range(3))  # type: ignore[return-value]
        prev_pos, prev_col = pos, col
    return prev_col


def vertical_gradient(size: tuple[int, int], stops: Sequence[tuple[float, str | Color]]) -> Image.Image:
    width, height = size
    column = Image.new("RGB", (1, height))
    px = column.load()
    denom = max(1, height - 1)
    for y in range(height):
        px[0, y] = sample_stops(stops, y / denom)
    return column.resize((width, height), Image.Resampling.NEAREST)


def paste_periodic(dst: Image.Image, tile: Image.Image, offset: float, y: int = 0) -> None:
    """Paste an RGBA ``tile`` repeatedly across ``dst`` so that it scrolls left by ``offset``."""
    tw = tile.width
    x = -(int(round(offset)) % tw)
    while x < dst.width:
        dst.paste(tile, (x, y), tile)
        x += tw


def downsample(image: Image.Image, factor: int) -> Image.Image:
    if factor == 1:
        return image
    size = (image.width // factor, image.height // factor)
    if image.mode == "RGBA":
        # Premultiply so transparent pixels do not bleed dark fringes into edges.
        return image.convert("RGBa").resize(size, Image.Resampling.BOX).convert("RGBA")
    return image.resize(size, Image.Resampling.BOX)


class Painter:
    """Draw in user coordinates; ``mapper`` converts them to pixels and ``scale`` is the
    number of pixels per user unit (for widths and radii)."""

    def __init__(
        self,
        image: Image.Image,
        scale: float,
        mapper: Callable[[float, float], Point] | None = None,
    ) -> None:
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.scale = scale
        self.mapper = mapper or (lambda x, y: (x * scale, y * scale))

    def pt(self, p: Point) -> Point:
        return self.mapper(p[0], p[1])

    def px(self, width: float) -> int:
        return max(1, round(width * self.scale))

    def disc(self, c: Point, r: float, fill: Color) -> None:
        x, y = self.pt(c)
        rr = r * self.scale
        self.draw.ellipse((x - rr, y - rr, x + rr, y + rr), fill=fill)

    def ring(self, c: Point, r: float, width: float, color: Color) -> None:
        x, y = self.pt(c)
        rr = r * self.scale
        self.draw.ellipse((x - rr, y - rr, x + rr, y + rr), outline=color, width=self.px(width))

    def line(self, a: Point, b: Point, width: float, color: Color, caps: bool = True) -> None:
        pa, pb = self.pt(a), self.pt(b)
        w = self.px(width)
        self.draw.line([pa, pb], fill=color, width=w)
        if caps and w > 2:
            r = w / 2.0
            for x, y in (pa, pb):
                self.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def polyline(self, pts: Sequence[Point], width: float, color: Color) -> None:
        mapped = [self.pt(p) for p in pts]
        w = self.px(width)
        self.draw.line(mapped, fill=color, width=w, joint="curve")
        if w > 2:
            r = w / 2.0
            for x, y in (mapped[0], mapped[-1]):
                self.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def poly(self, pts: Sequence[Point], fill: Color, edge: Color | None = None, edge_w: float = 0.0) -> None:
        mapped = [self.pt(p) for p in pts]
        if edge is not None and edge_w > 0:
            self.draw.line(mapped + [mapped[0]], fill=edge, width=self.px(2 * edge_w), joint="curve")
        self.draw.polygon(mapped, fill=fill)

    def limb(self, segments: Sequence[tuple[Point, Point, float, Color]], edge: Color, edge_w: float) -> None:
        """A limb made of capsules: one merged outline underneath, then the fills."""
        for a, b, w, _ in segments:
            self.line(a, b, w + 2 * edge_w, edge)
        for a, b, w, fill in segments:
            self.line(a, b, w, fill)


def regular_arc(center: Point, radius: float, a0: float, a1: float, steps: int) -> list[Point]:
    """Points on an arc (math convention: counter-clockwise from +x, y up)."""
    return [
        (
            center[0] + radius * math.cos(a0 + (a1 - a0) * i / steps),
            center[1] + radius * math.sin(a0 + (a1 - a0) * i / steps),
        )
        for i in range(steps + 1)
    ]
