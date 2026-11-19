"""Sky, sun/moon, stars, clouds, parallax mountains and weather.

Every scrolling layer is a tile whose width equals ``parallax * lap_length`` pixels and
whose scroll offset is ``rider_x / lap_length * tile_width``. One lap therefore scrolls
exactly one whole tile, so the last frame lines up with the first and nothing teleports.
Weather and twinkling use whole numbers of cycles per loop for the same reason.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from commit_rider.animation.engine import FrameState
from commit_rider.rendering.colors import darken, lighten, mix, rgb
from commit_rider.rendering.drawing import Painter, paste_periodic, vertical_gradient
from commit_rider.rendering.themes import LayerSpec, Theme

CLOUD_PARALLAX = 0.18


def ridge_profile(samples: int, seed: int, kind: str) -> list[float]:
    """Periodic ridge heights in 0..1 built from integer-cycle sines (so tiles join)."""
    rng = random.Random(seed)
    parts = [(k, rng.random() * math.tau, 1.0 / k**1.05) for k in range(2, 27) if rng.random() < 0.82]
    raw = [sum(a * math.sin(math.tau * k * i / samples + ph) for k, ph, a in parts) for i in range(samples)]
    peak = max(abs(v) for v in raw) or 1.0
    norm = [v / peak for v in raw]
    if kind == "mountains":
        return [(1.0 - abs(v)) ** 1.35 for v in norm]
    return [0.5 + 0.5 * v for v in norm]


class Background:
    def __init__(
        self,
        theme: Theme,
        size: tuple[int, int],
        ppu: float,
        lap_length: float,
        duration: float,
        cam_ref: float,
        seed: int = 0,
    ) -> None:
        self.theme = theme
        self.w, self.h = size
        self.ppu = ppu
        self.lap_length = lap_length
        self.cam_ref = cam_ref
        self.seed = seed
        rng = random.Random(seed * 131 + 7)
        self.sky = self._build_sky(rng)
        self.layers: list[tuple[LayerSpec, Image.Image]] = [
            (spec, self._build_layer(spec)) for spec in theme.layers
        ]
        self.clouds = self._build_clouds(rng) if theme.clouds else None
        self.haze = self._build_haze() if theme.haze else None
        self.twinkle = [
            (rng.random() * self.w, rng.random() * self.h * 0.55, rng.randint(1, 3), rng.random())
            for _ in range(min(theme.stars, 26))
        ] if theme.stars else []
        self.flakes = (
            [
                (rng.random(), rng.random(), rng.uniform(0.9, 2.2), rng.choice((2, 3, 3, 4)),
                 rng.uniform(0.004, 0.014), rng.randint(1, 3), rng.random())
                for _ in range(90)
            ]
            if theme.falling_snow
            else []
        )

    # ----- static pieces --------------------------------------------------------
    def _build_sky(self, rng: random.Random) -> Image.Image:
        theme = self.theme
        sky = vertical_gradient((self.w, self.h), theme.sky)
        if theme.stars:
            painter = Painter(sky, self.ppu)
            star = rgb(theme.star_color)
            horizon = self.h * 0.62
            for _ in range(theme.stars):
                x = rng.random() * self.w
                y = rng.random() * horizon * 0.95
                fade = 1.0 - y / horizon
                color = mix(painter.image.getpixel((int(x), int(y))), star, 0.35 + 0.6 * fade)
                r = rng.choice((0.5, 0.5, 0.7, 0.9)) * self.ppu
                painter.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
        if theme.celestial != "none":
            self._celestial(sky)
        return sky

    def _celestial(self, sky: Image.Image) -> None:
        theme = self.theme
        cx = theme.celestial_pos[0] * self.w
        cy = theme.celestial_pos[1] * self.h
        r = theme.celestial_radius * self.ppu
        glow_r = int(r * 4.2)
        # radial_gradient reaches 255 only at the *corners*; rescale so 255 sits at radius.
        glow = Image.radial_gradient("L").point(lambda v: min(255, int(v * 1.4143)))
        glow = glow.resize((glow_r * 2, glow_r * 2), Image.Resampling.BILINEAR)
        glow = ImageChops.invert(glow).point(lambda v: int((v / 255.0) ** 2.2 * 115))
        tint = Image.new("RGB", glow.size, rgb(theme.celestial_glow))
        sky.paste(tint, (int(cx - glow_r), int(cy - glow_r)), glow)
        body = Image.new("RGB", (int(r * 2) + 2, int(r * 2) + 2))
        top, bottom = rgb(theme.celestial_color), rgb(theme.celestial_glow)
        body = vertical_gradient(body.size, [(0.0, top), (1.0, mix(top, bottom, 0.55 if theme.sun_stripes else 0.0))])
        mask = Image.new("L", body.size, 0)
        md = ImageDraw.Draw(mask)
        md.ellipse((1, 1, body.width - 2, body.height - 2), fill=255)
        if theme.sun_stripes:
            for i in range(6):
                y0 = body.height * (0.50 + 0.075 * i)
                md.rectangle((0, y0, body.width, y0 + body.height * (0.012 + 0.012 * i)), fill=0)
        if theme.celestial == "moon":
            md.ellipse((body.width * 0.32, body.height * 0.02, body.width * 1.05, body.height * 0.92), fill=0)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=0.6))
        sky.paste(body, (int(cx - body.width / 2), int(cy - body.height / 2)), mask)

    def _build_layer(self, spec: LayerSpec) -> Image.Image:
        tile_w = max(8, round(spec.parallax * self.lap_length * self.ppu))
        tile_h = int(self.h * 1.6)
        values = ridge_profile(tile_w, spec.seed + self.seed * 17, spec.kind)
        base = spec.base * self.h
        amp = spec.amplitude * self.ppu
        ys = [base - amp * v for v in values]
        top = rgb(spec.color)
        fill = vertical_gradient((tile_w, tile_h), [(0.0, lighten(top, 0.06)), (spec.base * 0.6 + 0.45, top), (1.0, darken(top, 0.18))])
        mask = Image.new("L", (tile_w, tile_h), 0)
        pts = [(i, ys[i]) for i in range(tile_w)] + [(tile_w - 1, tile_h), (0, tile_h)]
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
        tile.paste(fill, (0, 0), mask)
        draw = ImageDraw.Draw(tile)
        if spec.snow:
            cap = lighten(self.theme.layers[0].color, 0.8)
            rng = random.Random(spec.seed)
            i = 0
            while i < tile_w:
                if values[i] > 0.74:
                    j = i
                    while j < tile_w and values[j] > 0.74:
                        j += 1
                    top_pts = [(x, ys[x]) for x in range(i, j)]
                    bottom = [(x, ys[x] + (values[x] - 0.74) * amp * 1.5 * (0.8 + 0.4 * rng.random())) for x in range(j - 1, i - 1, -1)]
                    if len(top_pts) > 2:
                        draw.polygon(top_pts + bottom, fill=cap + (255,))
                    i = j
                else:
                    i += 1
        if spec.rim:
            line_pts = [(i, ys[i]) for i in range(0, tile_w, 2)]
            draw.line(line_pts, fill=rgb(spec.rim) + (255,), width=max(1, round(1.4 * self.ppu)), joint="curve")
        return tile

    def _build_clouds(self, rng: random.Random) -> Image.Image:
        theme = self.theme
        tile_w = max(8, round(CLOUD_PARALLAX * self.lap_length * self.ppu))
        tile = Image.new("RGBA", (tile_w, int(self.h * 0.6)), (0, 0, 0, 0))
        painter = Painter(tile, self.ppu)
        color = rgb(theme.cloud_color)
        count = max(2, round(theme.clouds * tile_w / self.w))
        for k in range(count):
            cx = (k + rng.uniform(0.15, 0.85)) / count * tile_w
            cy = rng.uniform(0.10, 0.36) * self.h
            scale = rng.uniform(0.8, 1.5)
            painter.draw.ellipse(
                (cx - 38 * scale * self.ppu, cy - 5 * scale * self.ppu, cx + 38 * scale * self.ppu, cy + 8 * scale * self.ppu),
                fill=color,
            )
            for dx, dy, rad in ((-18, -4, 10), (-4, -10, 14), (13, -5, 11), (24, 0, 7)):
                r = rad * scale * self.ppu
                x, y = cx + dx * scale * self.ppu, cy + dy * scale * self.ppu
                painter.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
        alpha = tile.getchannel("A").point(lambda a: int(a * theme.cloud_alpha))
        tile.putalpha(alpha)
        return tile

    def _build_haze(self) -> Image.Image:
        theme = self.theme
        column = Image.new("L", (1, self.h))
        px = column.load()
        for y in range(self.h):
            t = (y / self.h - 0.50) / 0.30
            t = min(1.0, max(0.0, t))
            px[0, y] = int(255 * theme.haze_alpha * t * t * (3 - 2 * t))
        alpha = column.resize((self.w, self.h), Image.Resampling.NEAREST)
        overlay = Image.new("RGBA", (self.w, self.h), rgb(theme.haze) + (0,))
        overlay.putalpha(alpha)
        return overlay

    # ----- per frame ---------------------------------------------------------------
    def draw(self, canvas: Image.Image, frame: FrameState, loop_fraction: float) -> None:
        """Draw sky, weather, parallax layers and haze onto ``canvas`` (supersampled RGB)."""
        canvas.paste(self.sky)
        draw = ImageDraw.Draw(canvas, "RGBA")
        theme = self.theme
        for x, y, cycles, phase in self.twinkle:
            level = 0.55 + 0.45 * math.sin(math.tau * (cycles * loop_fraction + phase))
            r = 1.1 * self.ppu
            color = rgb(theme.star_color) + (int(255 * level),)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

        lap_frac = frame.x_mid / self.lap_length
        dcam = frame.cam_y - self.cam_ref
        if self.clouds is not None:
            tile = self.clouds
            paste_periodic(canvas, tile, lap_frac * tile.width, int(dcam * self.ppu * 0.06))
        for spec, tile in self.layers:
            dy = int(round(dcam * self.ppu * 0.5 * spec.parallax))
            paste_periodic(canvas, tile, lap_frac * tile.width, dy)
        if self.haze is not None:
            canvas.paste(self.haze, (0, 0), self.haze)
        self._snow(canvas, loop_fraction)

    def _snow(self, canvas: Image.Image, u: float) -> None:
        if not self.flakes:
            return
        draw = ImageDraw.Draw(canvas, "RGBA")
        for x0, y0, size, fall, sway, cycles, phase in self.flakes:
            y = ((y0 + fall * u) % 1.0) * self.h
            x = (x0 + sway * math.sin(math.tau * (cycles * u + phase))) % 1.0 * self.w
            r = size * self.ppu * 0.8
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 215))
