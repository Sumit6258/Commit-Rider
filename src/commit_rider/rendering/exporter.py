"""GIF export: one global palette, inter-frame transparency, validation.

Why not just ``Image.save(save_all=True)``? Pillow writes each frame with its own
analysis and only crops to the changed bounding box. A side-scroller changes almost every
pixel of the moving parts but not the sky, so this module:

1. builds *one* palette for the whole animation (no colour flicker between frames);
2. maps every frame to it without dithering (dither noise would crawl as the scene scrolls);
3. marks pixels that did not change as transparent (disposal 1: "leave in place"), which
   LZW compresses to almost nothing;
4. lets Pillow's C encoder do the LZW work, then assembles the container itself.

If the result is larger than the requested limit it retries with a smaller palette and a
small colour tolerance, and reports exactly what it did.
"""

from __future__ import annotations

import io
import logging
import os
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops

from commit_rider.errors import OutputError

log = logging.getLogger("commit_rider")

TRANSPARENT_INDEX = 255
MIB = 1024 * 1024
# (colours, tolerance) tried in order until the size limit is met.
STRATEGIES: tuple[tuple[int, int], ...] = ((255, 0), (255, 3), (192, 5), (128, 7), (96, 9), (64, 12))


@dataclass
class ExportReport:
    path: Path
    frames: int
    width: int
    height: int
    duration_ms: int
    loop: int | None
    size_bytes: int
    colors: int = 0
    tolerance: int = 0
    attempts: list[str] = field(default_factory=list)
    within_limit: bool = True

    @property
    def size_mb(self) -> float:
        return self.size_bytes / MIB


# --------------------------------------------------------------------------- palette
def build_palette(
    frames: Sequence[Image.Image], colors: int, key_colors: Sequence[tuple[int, int, int]] = ()
) -> list[int]:
    """A flat 768-entry palette list for the whole animation.

    The palette is median-cut over a mosaic of evenly spaced frames; ``key_colors`` (the
    rider and bicycle colours) are appended verbatim so small but important objects can
    never lose their exact colours to the large background areas.
    """
    if not 2 <= colors <= 255:
        raise ValueError("colors must be between 2 and 255")
    keys = list(dict.fromkeys(tuple(c) for c in key_colors))[: max(0, colors // 4)]
    sample_count = min(len(frames), 10)
    picks = sorted({round(i * (len(frames) - 1) / max(1, sample_count - 1)) for i in range(sample_count)})
    w, h = frames[0].size
    mosaic = Image.new("RGB", (w, h * len(picks)))
    for row, index in enumerate(picks):
        mosaic.paste(frames[index], (0, row * h))
    quantized = mosaic.quantize(colors=colors - len(keys), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw = quantized.getpalette() or []
    used = len(raw) // 3
    entries = [tuple(raw[i * 3 : i * 3 + 3]) for i in range(min(used, colors - len(keys)))]
    entries += [k for k in keys if k not in entries]
    flat: list[int] = []
    for entry in entries[:colors]:
        flat.extend(entry)
    flat.extend([0] * (768 - len(flat)))
    return flat


def _palette_image(flat: list[int]) -> Image.Image:
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


# --------------------------------------------------------------------------- encoding
def _lzw_block(indexed: Image.Image) -> bytes:
    """LZW-compressed image data (min code size + sub-blocks + terminator) for ``indexed``.

    Pillow's C encoder produces a complete one-frame GIF; the image-data section is cut out
    and re-used verbatim in our container.
    """
    buffer = io.BytesIO()
    indexed.save(buffer, format="GIF", optimize=False, interlace=False)
    blob = buffer.getvalue()
    pos = 13
    packed = blob[10]
    if packed & 0x80:
        pos += 3 * (2 << (packed & 7))
    while blob[pos] == 0x21:  # skip extension blocks
        pos += 2
        while blob[pos] != 0:
            pos += blob[pos] + 1
        pos += 1
    if blob[pos] != 0x2C:
        raise OutputError("Unexpected structure in Pillow's GIF output")
    ipacked = blob[pos + 9]
    if ipacked & 0x40:
        raise OutputError("Pillow produced an interlaced frame; rows would be out of order")
    pos += 10
    if ipacked & 0x80:
        pos += 3 * (2 << (ipacked & 7))
    if blob[-1] != 0x3B:
        raise OutputError("Pillow's GIF output has no trailer")
    return blob[pos:-1]


def _delays_cs(count: int, fps: float) -> list[int]:
    """Per-frame delays in centiseconds whose running sum tracks ``count * 100 / fps``."""
    out, prev = [], 0
    for i in range(count):
        cur = round((i + 1) * 100.0 / fps)
        out.append(max(2, cur - prev))
        prev = cur
    return out


def _as_l(image: Image.Image) -> Image.Image:
    return Image.frombytes("L", image.size, image.tobytes())


def encode_gif(
    frames: Sequence[Image.Image], fps: float, colors: int = 255, tolerance: int = 0,
    key_colors: Sequence[tuple[int, int, int]] = (), loop: int = 0,
) -> tuple[bytes, int]:
    """Encode RGB frames; returns ``(gif_bytes, palette_colours_used)``."""
    if not frames:
        raise OutputError("No frames to encode")
    size = frames[0].size
    if any(f.size != size or f.mode != "RGB" for f in frames):
        raise OutputError("All frames must be RGB images of identical size")
    flat = build_palette(frames, colors, key_colors)
    pal_img = _palette_image(flat)
    delays = _delays_cs(len(frames), fps)
    width, height = size

    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width, height, 0xF7, 0, 0)
    out += bytes(flat)
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00"

    lut_near = [255 if v <= tolerance else 0 for v in range(256)]
    lut_equal = [255] + [0] * 255
    prev_idx: Image.Image | None = None
    ref_rgb: Image.Image | None = None  # original colour of each pixel when it was last written
    min_code = None
    for index, frame in enumerate(frames):
        cur_p = frame.quantize(palette=pal_img, dither=Image.Dither.NONE)
        cur_idx = _as_l(cur_p)
        if prev_idx is None or ref_rgb is None:
            shown_idx = cur_idx
            ref_rgb = frame
            left = top = 0
            region = cur_idx
            transparent = False
        else:
            unchanged = ImageChops.difference(cur_idx, prev_idx).point(lut_equal)
            if tolerance > 0:
                r, g, b = ImageChops.difference(frame, ref_rgb).split()
                near = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lut_near)
                unchanged = ImageChops.lighter(unchanged, near)
            shown_idx = Image.composite(prev_idx, cur_idx, unchanged)
            ref_rgb = Image.composite(ref_rgb, frame, unchanged)
            delta = shown_idx.copy()
            delta.paste(TRANSPARENT_INDEX, mask=unchanged)
            bbox = ImageChops.invert(unchanged).getbbox()
            if bbox is None:  # identical frame: a 1x1 fully transparent patch keeps the timing
                left = top = 0
                region = Image.new("L", (1, 1), TRANSPARENT_INDEX)
            else:
                left, top = bbox[0], bbox[1]
                region = delta.crop(bbox)
            transparent = True
        region_p = Image.frombytes("P", region.size, region.tobytes())
        region_p.putpalette(flat)
        data = _lzw_block(region_p)
        if min_code is None:
            min_code = data[0]
        elif data[0] != min_code:
            raise OutputError("Inconsistent LZW code size between frames")
        packed = (1 << 2) | (1 if transparent else 0)
        out += b"\x21\xf9\x04" + bytes([packed]) + struct.pack("<H", delays[index]) + bytes([TRANSPARENT_INDEX, 0])
        out += b"\x2c" + struct.pack("<HHHH", left, top, region.width, region.height) + b"\x00"
        out += data
        prev_idx = shown_idx
    out += b"\x3b"
    return bytes(out), len(flat) // 3


# --------------------------------------------------------------------------- export
def export_gif(
    frames: Sequence[Image.Image],
    path: str | os.PathLike[str],
    fps: float,
    *,
    colors: int = 255,
    tolerance: int = 0,
    max_bytes: int | None = None,
    key_colors: Sequence[tuple[int, int, int]] = (),
) -> ExportReport:
    """Write ``frames`` as a looping GIF, shrinking quality step by step to fit ``max_bytes``."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Cannot create output directory {target.parent}: {exc}") from None

    plan = [(colors, tolerance)] + [s for s in STRATEGIES if s[0] <= colors and s != (colors, tolerance) and (s[0] < colors or s[1] > tolerance)]
    attempts: list[str] = []
    best: tuple[bytes, int, int, int] | None = None
    for n_colors, tol in plan:
        data, used = encode_gif(frames, fps, n_colors, tol, key_colors)
        attempts.append(f"{n_colors} colours, tolerance {tol}: {len(data) / MIB:.2f} MiB")
        log.debug("GIF attempt %s", attempts[-1])
        if best is None or len(data) < len(best[0]):
            best = (data, n_colors, tol, used)
        if max_bytes is None or len(data) <= max_bytes:
            best = (data, n_colors, tol, used)
            break
    assert best is not None
    data, n_colors, tol, _ = best
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise OutputError(f"Cannot write {target}: {exc}") from None
    try:
        report = validate_gif(target, expected_size=frames[0].size, expected_frames=len(frames), expected_fps=fps)
    except OutputError:
        target.unlink(missing_ok=True)  # never leave a broken animation behind
        raise
    report.colors, report.tolerance, report.attempts = n_colors, tol, attempts
    report.within_limit = max_bytes is None or report.size_bytes <= max_bytes
    if not report.within_limit:
        log.warning(
            "GIF is %.2f MiB, above the %.2f MiB limit even at the lowest quality tried; "
            "lower the size, fps or duration to shrink it.", report.size_mb, (max_bytes or 0) / MIB,
        )
    return report


def save_preview(image: Image.Image, path: str | os.PathLike[str]) -> Path:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG", optimize=True)
    except OSError as exc:
        raise OutputError(f"Cannot write preview {target}: {exc}") from None
    return target


# ------------------------------------------------------------------------- validation
def validate_gif(
    path: str | os.PathLike[str],
    expected_size: tuple[int, int] | None = None,
    expected_frames: int | None = None,
    expected_fps: float | None = None,
) -> ExportReport:
    """Re-open the file with Pillow and check dimensions, frame count, timing, looping and
    that no frame is blank. Raises :class:`OutputError` describing the first problem."""
    target = Path(path)
    try:
        size_bytes = target.stat().st_size
        im = Image.open(target)
    except (OSError, ValueError) as exc:
        raise OutputError(f"{target} is not a readable image: {exc}") from None
    try:
        if im.format != "GIF":
            raise OutputError(f"{target} is {im.format}, not GIF")
        n = getattr(im, "n_frames", 1)
        if expected_size and im.size != tuple(expected_size):
            raise OutputError(f"GIF is {im.size}, expected {tuple(expected_size)}")
        if expected_frames is not None and n != expected_frames:
            raise OutputError(f"GIF has {n} frames, expected {expected_frames}")
        loop = im.info.get("loop")
        if loop != 0:
            raise OutputError(f"GIF loop count is {loop!r}; expected 0 (infinite)")
        total_ms = 0
        for i in range(n):
            im.seek(i)
            total_ms += int(im.info.get("duration", 0))
            low, high = im.convert("RGB").getextrema()[0]
            if n > 1 and i in (0, n // 2, n - 1) and low == high:
                raise OutputError(f"Frame {i} is blank")
        if expected_fps and expected_frames:
            ideal = expected_frames * 1000.0 / expected_fps
            if abs(total_ms - ideal) > max(20.0, 0.02 * ideal):
                raise OutputError(f"GIF lasts {total_ms} ms, expected about {ideal:.0f} ms")
        width, height = im.size
    finally:
        im.close()
    return ExportReport(path=target, frames=n, width=width, height=height, duration_ms=total_ms, loop=loop, size_bytes=size_bytes)
