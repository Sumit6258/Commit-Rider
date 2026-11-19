"""End-to-end generation: series + settings -> validated GIF (+ PNG preview)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from commit_rider.config.settings import Settings
from commit_rider.data.models import ContributionSeries
from commit_rider.data.stats import ContributionStats
from commit_rider.errors import OutputError, RenderError
from commit_rider.rendering.colors import rgb
from commit_rider.rendering.exporter import ExportReport, export_gif, save_preview
from commit_rider.rendering.renderer import Renderer
from commit_rider.rendering.themes import Theme

log = logging.getLogger("commit_rider")


@dataclass
class GenerationResult:
    report: ExportReport
    preview_path: Path | None
    stats: ContributionStats
    series: ContributionSeries
    summary: dict[str, float | int]
    seconds: float


def check_output_path(path: str | os.PathLike[str]) -> Path:
    """Fail early (before rendering) if the output cannot be written."""
    target = Path(path)
    if target.suffix.lower() != ".gif":
        raise OutputError(f"The output file must end in .gif (got {target.name!r})")
    if target.exists() and target.is_dir():
        raise OutputError(f"{target} is a directory; give a file name ending in .gif")
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Cannot create the output directory {parent}: {exc}") from None
    if not os.access(parent, os.W_OK):
        raise OutputError(f"The output directory {parent} is not writable")
    return target


def key_colors(theme: Theme) -> list[tuple[int, int, int]]:
    names = ("jersey", "helmet", "skin", "shorts", "shoes", "glove", "frame", "fork", "rim", "tire",
             "spoke", "saddle", "chain", "ink", "terrain_edge", "overlay_accent")
    colors = [rgb(getattr(theme, name)) for name in names]
    colors += [rgb(c) for c in theme.trail]
    return colors


def generate(
    series: ContributionSeries,
    settings: Settings,
    output: str | os.PathLike[str],
    *,
    preview: bool | str | os.PathLike[str] = True,
    theme: Theme | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> GenerationResult:
    started = time.monotonic()
    target = check_output_path(output)
    preview_target: Path | None = None
    if preview:
        preview_target = target.with_suffix(".png") if preview is True else Path(preview)

    try:
        renderer = Renderer(series, settings, theme)
        total = settings.frames
        frames = []
        for k in range(total):
            frames.append(renderer.render_frame(k))
            if progress:
                progress(k + 1, total)
    except OutputError:
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain error with context
        raise RenderError(f"Rendering failed at frame {len(frames) if 'frames' in locals() else 0}: {exc}") from exc

    preset = settings.quality_preset
    report = export_gif(
        frames, target, settings.fps,
        colors=preset.colors, tolerance=preset.tolerance,
        max_bytes=int(settings.max_size_mb * 1024 * 1024),
        key_colors=key_colors(renderer.theme),
    )
    if preview_target is not None:
        save_preview(frames[renderer.preview_index()], preview_target)
    return GenerationResult(
        report=report,
        preview_path=preview_target,
        stats=renderer.stats,
        series=series,
        summary=renderer.timeline.summary(),
        seconds=time.monotonic() - started,
    )
