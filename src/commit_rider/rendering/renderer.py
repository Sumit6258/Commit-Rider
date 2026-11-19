"""Frame renderer: composes background, terrain, shadow, dust, sprites and overlay."""

from __future__ import annotations

import math
from collections.abc import Iterator

from PIL import Image, ImageDraw

from commit_rider.animation import camera as cam
from commit_rider.animation.cyclist import RiderSpec
from commit_rider.animation.engine import Timeline
from commit_rider.config.settings import Settings
from commit_rider.data.models import ContributionSeries
from commit_rider.data.stats import compute_stats
from commit_rider.rendering.background import Background
from commit_rider.rendering.colors import rgb
from commit_rider.rendering.drawing import downsample, paste_periodic
from commit_rider.rendering.overlay import StatsOverlay
from commit_rider.rendering.sprites import SpriteRenderer
from commit_rider.rendering.terrain_layer import build_terrain_strip
from commit_rider.rendering.themes import Theme, get_theme
from commit_rider.terrain.generator import generate_terrain, params_from_settings


class Renderer:
    def __init__(self, series: ContributionSeries, settings: Settings, theme: Theme | None = None) -> None:
        self.series = series
        self.settings = settings
        base = theme or get_theme(settings.theme)
        self.theme = base.with_overrides(
            settings.bike_color, settings.rider_color, settings.terrain_color, settings.background_color
        )
        self.terrain = generate_terrain(series.counts, params_from_settings(settings))
        self.timeline = Timeline(self.terrain, settings)
        self.ss = settings.quality_preset.supersample
        self.unit = settings.unit
        self.ppu = self.unit * self.ss
        self.size = (settings.width * self.ss, settings.height * self.ss)
        cam_y = self.timeline.cam_y
        self.background = Background(
            self.theme, self.size, self.ppu, self.terrain.period, self.timeline.duration,
            cam_ref=sum(cam_y) / len(cam_y), seed=settings.seed,
        )
        view_h = settings.height / self.unit
        self.strip = build_terrain_strip(
            self.terrain, self.theme, self.ppu, min(cam_y), max(cam_y), view_h, cam.ANCHOR_Y, settings.seed
        )
        self.sprites = SpriteRenderer(self.theme, settings, self.timeline.bike, RiderSpec())
        self.stats = compute_stats(series)
        self.overlay = (
            StatsOverlay(series, self.stats, self.theme, (settings.width, settings.height), self.unit)
            if settings.show_stats
            else None
        )
        self._dust = rgb(self.theme.dust)
        self._ink = rgb(self.theme.ink)

    # ------------------------------------------------------------------------------
    def _screen(self, x: float, y: float, frame) -> tuple[float, float]:
        return (
            (x - frame.cam_x) * self.ppu,
            cam.ANCHOR_Y * self.size[1] - (y - frame.cam_y) * self.ppu,
        )

    def _shadow(self, canvas: Image.Image, frame) -> None:
        x = frame.x_mid
        ground = self.terrain.height(x)
        angle = math.atan(self.terrain.slope(x))
        k = 1.0 / (1.0 + 0.016 * frame.air_height)
        half_w = 44.0 * k
        half_h = 3.4 * k
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        pts = []
        for i in range(28):
            t = math.tau * i / 28
            ex, ey = half_w * math.cos(t), half_h * math.sin(t)
            pts.append(self._screen(x + ex * cos_a - ey * sin_a, ground + ex * sin_a + ey * cos_a, frame))
        ImageDraw.Draw(canvas, "RGBA").polygon(pts, fill=self._ink + (round(95 * k),))

    def _dust_puffs(self, canvas: Image.Image, frame) -> None:
        tl = self.timeline
        laps, t = divmod(frame.t, tl.duration)
        draw = ImageDraw.Draw(canvas, "RGBA")
        width, height = canvas.size
        for puff in tl.puffs:
            state = puff.at(t, tl.duration, tl.period)
            if state is None:
                continue
            x, y, radius, alpha = state
            sx, sy = self._screen(x + laps * tl.period, y, frame)
            r = radius * self.ppu
            if sx < -r or sx > width + r or sy < -r or sy > height + r:
                continue
            draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=self._dust + (round(255 * min(1.0, alpha)),))

    def render_frame(self, k: int) -> Image.Image:
        tl = self.timeline
        frame = tl.frame(k)
        canvas = Image.new("RGB", self.size)
        self.background.draw(canvas, frame, (k / tl.frames) % 1.0)
        y_off = round(cam.ANCHOR_Y * self.size[1] - (self.strip.y_top - frame.cam_y) * self.ppu)
        paste_periodic(canvas, self.strip.image, frame.cam_x * self.strip.kx, y_off)
        self._shadow(canvas, frame)
        if self.settings.particles:
            self._dust_puffs(canvas, frame)
        image = downsample(canvas, self.ss)
        self.sprites.draw(image, frame)
        if self.overlay is not None:
            self.overlay.apply(image, frame)
        return image

    def frames(self) -> Iterator[Image.Image]:
        for k in range(self.settings.frames):
            yield self.render_frame(k)

    def preview_index(self) -> int:
        """The frame to use for the still preview: the highest point of the best jump,
        or the middle of the lap if there are no jumps."""
        tl = self.timeline
        best, best_k = 0.0, tl.frames // 3
        for k in range(tl.frames):
            h = tl.frame(k).air_height
            if h > best:
                best, best_k = h, k
        return best_k
