"""Regenerate the images shipped in examples/ (run from the repository root).

    python tools/make_examples.py

* examples/demo.gif      the default ride, from examples/sample-contributions.json
* examples/preview.png   its PNG still
* examples/themes/*.png  one still per theme (same ride, same moment)

All of it is generated from *synthetic* sample data, not from anyone's real activity.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

from commit_rider.config.settings import Settings
from commit_rider.data.demo import generate_demo_series
from commit_rider.rendering.renderer import Renderer
from commit_rider.rendering.themes import theme_names

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def main() -> int:
    EXAMPLES.mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "commit_rider", "--input-json", str(EXAMPLES / "sample-contributions.json"),
         "--output", str(EXAMPLES / "demo.gif"), "--preview", str(EXAMPLES / "preview.png")],
        check=True,
    )
    themes_dir = EXAMPLES / "themes"
    themes_dir.mkdir(exist_ok=True)
    series = generate_demo_series()
    for name in theme_names():
        renderer = Renderer(series, Settings(theme=name))
        image = renderer.render_frame(renderer.preview_index())
        # 8-bit PNG keeps the repository small; the GIF is 8-bit anyway.
        image.quantize(colors=192, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
            themes_dir / f"{name}.png", optimize=True
        )
        print(f"wrote examples/themes/{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
