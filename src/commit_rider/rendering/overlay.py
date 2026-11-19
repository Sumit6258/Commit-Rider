"""Optional statistics overlay and date ticker (hidden unless ``show_stats`` is on)."""

from __future__ import annotations

import datetime as dt

from PIL import Image, ImageDraw, ImageFont

from commit_rider.animation.engine import FrameState
from commit_rider.data.models import ContributionSeries
from commit_rider.data.stats import ContributionStats
from commit_rider.rendering.colors import rgb
from commit_rider.rendering.themes import Theme

_FONT_CANDIDATES = (
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
)
_BOLD_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
)


def load_font(size: float, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """A TrueType font if one is installed, otherwise Pillow's built-in scalable font."""
    px = max(6, round(size))
    for name in (_BOLD_CANDIDATES if bold else ()) + _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # very old Pillow: fixed-size bitmap font
        return ImageFont.load_default()


def _date(d: dt.date) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


class StatsOverlay:
    def __init__(self, series: ContributionSeries, stats: ContributionStats, theme: Theme, size: tuple[int, int], unit: float) -> None:
        self.series = series
        self.theme = theme
        self.size = size
        self.unit = unit
        self.accent = rgb(theme.overlay_accent)
        self.text = rgb(theme.overlay_text)
        self.small = load_font(11 * unit)
        self.big = load_font(18 * unit, bold=True)
        self.panel = self._build_panel(stats)

    def _build_panel(self, stats: ContributionStats) -> Image.Image:
        u = self.unit
        lines = [
            (self.big, f"{stats.total:,} contributions", 1.0),
            (self.small, f"{_date(stats.start)} \u2013 {_date(stats.end)}", 0.72),
            (
                self.small,
                f"Best day {stats.max_count} ({stats.max_date.strftime('%b')} {stats.max_date.day})"
                f"  \u00b7  avg {stats.average:.1f}/day  \u00b7  streak {stats.current_streak}",
                0.72,
            ),
        ]
        if stats.restricted:
            lines.append((self.small, f"+{stats.restricted:,} private (aggregate, not in terrain)", 0.55))
        probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        widths = [probe.textlength(text, font=font) for font, text, _ in lines]
        pad = 10 * u
        heights = [f.size * 1.32 if hasattr(f, "size") else 14 for f, _, _ in lines]
        w, h = int(max(widths) + 2 * pad + 6 * u), int(sum(heights) + 1.6 * pad)
        panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(panel)
        bg = rgb(self.theme.overlay_bg)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8 * u, fill=bg + (round(255 * self.theme.overlay_alpha),))
        d.rounded_rectangle((0, 0, 4 * u, h - 1), radius=2 * u, fill=self.accent + (255,))
        y = 0.8 * pad
        for (font, text, strength), line_h in zip(lines, heights, strict=True):
            color = self.text if strength >= 1.0 else tuple(round(self.text[i] * strength + bg[i] * (1 - strength)) for i in range(3))
            d.text((pad + 5 * u, y), text, font=font, fill=color + (255,))
            y += line_h
        return panel

    def apply(self, image: Image.Image, frame: FrameState) -> None:
        u = self.unit
        image.paste(self.panel, (round(12 * u), round(12 * u)), self.panel)
        draw = ImageDraw.Draw(image, "RGBA")
        n = len(self.series)
        idx = frame.day_index
        fraction = (idx + 0.5) / n if idx is not None else (0.0 if frame.progress < 0.5 else 1.0)
        bar_h = max(2, round(3 * u))
        w, h = image.size
        draw.rectangle((0, h - bar_h, w, h), fill=rgb(self.theme.overlay_bg) + (110,))
        draw.rectangle((0, h - bar_h, round(w * fraction), h), fill=self.accent + (255,))
        if idx is not None:
            label = _date(self.series.days[min(idx, n - 1)].date)
            tw = draw.textlength(label, font=self.small)
            x, y = w - tw - 14 * u, h - bar_h - 20 * u
            draw.rounded_rectangle((x - 7 * u, y - 3 * u, x + tw + 7 * u, y + 16 * u), radius=6 * u, fill=rgb(self.theme.overlay_bg) + (round(255 * self.theme.overlay_alpha),))
            draw.text((x, y), label, font=self.small, fill=self.accent + (255,))
