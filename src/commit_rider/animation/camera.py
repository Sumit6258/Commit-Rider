"""Camera: the rider stays near the left-centre of the frame while the world scrolls.

Both camera coordinates are pure functions of the rider's position along the (periodic)
track, so the camera is automatically continuous and loops without a jump. Vertical
motion follows a heavily smoothed copy of the ground height so hills are felt but the
rider never leaves the frame.
"""

from __future__ import annotations

from commit_rider.terrain.geometry import Terrain
from commit_rider.terrain.interpolation import smooth_circular

ANCHOR_X = 0.38  # rider's horizontal position as a fraction of the view width
ANCHOR_Y = 0.71  # screen row (fraction of height) where the camera's reference height sits
FOLLOW = 0.85  # fraction of the (smoothed) ground height change the camera follows
AIR_FREE = 60.0  # jumps up to this height above the ground path do not move the camera
AIR_FOLLOW = 0.85  # beyond that, the camera rises with the rider so big air stays in frame


def camera_heights(
    terrain: Terrain, x_start: float, n: int, dx: float, air: list[float] | None = None
) -> list[float]:
    """Camera reference height per lap index. ``air`` is the rider's height above the
    ground-bound path (zero when riding on the ground)."""
    ground = [terrain.height(x_start + i * dx) for i in range(n)]
    smooth = smooth_circular(ground, 200.0 / dx)
    mean = sum(smooth) / n
    heights = [mean + FOLLOW * (v - mean) for v in smooth]
    if air is not None:
        raised = smooth_circular(air, 30.0 / dx)
        heights = [h + AIR_FOLLOW * max(0.0, a - AIR_FREE) for h, a in zip(heights, raised, strict=True)]
    return heights


def camera_x(x_mid: float, view_width: float) -> float:
    return x_mid - ANCHOR_X * view_width
