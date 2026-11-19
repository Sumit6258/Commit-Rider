"""Bicycle geometry.

Everything is in *bike-local* coordinates: origin at the rear axle, +x forward,
+y up, units are world units (about 1 cm; a wheel is 54 units across). The drawing code
maps these to the screen; nothing here knows about pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def _along(origin: Point, direction: Point, distance: float) -> Point:
    return (origin[0] + direction[0] * distance, origin[1] + direction[1] * distance)


@dataclass(frozen=True)
class BikeSpec:
    """A BMX-style dirt jumper: 54-unit wheels, riser bars, short frame, front suspension."""

    name: str = "bmx"
    wheel_radius: float = 27.0
    rim_radius: float = 20.5
    wheelbase: float = 104.0
    bb: Point = (41.0, 4.0)
    crank_length: float = 17.0
    chainring_radius: float = 10.5
    cog_radius: float = 4.8
    seat_tube_angle: float = math.radians(72.0)
    seat_tube_length: float = 33.0
    seat_post_length: float = 26.0
    head_angle: float = math.radians(71.0)
    fork_length: float = 42.0
    fork_lowers: float = 21.0
    head_tube_length: float = 12.0
    fork_travel: float = 9.0
    spokes: int = 20


@dataclass(frozen=True)
class BikePoints:
    """Named points of the bike for one suspension state."""

    rear_axle: Point
    front_axle: Point
    bb: Point
    seat_tube_top: Point
    seat_clamp: Point
    saddle_top: Point
    saddle_rear: Point
    saddle_nose: Point
    head_bottom: Point
    head_top: Point
    crown: Point
    lowers_top: Point
    top_tube_rear: Point
    top_tube_front: Point
    down_tube_front: Point
    seat_stay_top: Point
    stem_top: Point
    grip: Point
    lever_tip: Point
    steer_axis: Point  # unit vector from the front axle up along the steering axis


def bike_points(spec: BikeSpec, fork_compress: float = 0.0) -> BikePoints:
    """Return the bike's named points; ``fork_compress`` (0..1) shortens the fork."""
    fork_compress = min(1.0, max(0.0, fork_compress))
    rear = (0.0, 0.0)
    front = (spec.wheelbase, 0.0)
    u = (-math.cos(spec.head_angle), math.sin(spec.head_angle))  # axle -> crown direction
    v = (-math.cos(spec.seat_tube_angle), math.sin(spec.seat_tube_angle))

    fork_len = spec.fork_length - spec.fork_travel * fork_compress
    crown = _along(front, u, fork_len)
    lowers_top = _along(front, u, spec.fork_lowers)
    head_bottom = _along(crown, u, 1.5)
    head_top = _along(head_bottom, u, spec.head_tube_length)

    seat_top = _along(spec.bb, v, spec.seat_tube_length)
    clamp = _along(seat_top, v, spec.seat_post_length)
    saddle_top = _add(clamp, (0.0, 2.6))

    stem_top = _add(_along(head_top, u, 3.0), (2.5, 0.0))
    # Riser bar: up and slightly back from the stem; the grip is seen end-on.
    grip = _add(stem_top, (-7.0, 17.0))
    return BikePoints(
        rear_axle=rear,
        front_axle=front,
        bb=spec.bb,
        seat_tube_top=seat_top,
        seat_clamp=clamp,
        saddle_top=saddle_top,
        saddle_rear=_add(saddle_top, (-11.5, -1.2)),
        saddle_nose=_add(saddle_top, (12.5, -1.8)),
        head_bottom=head_bottom,
        head_top=head_top,
        crown=crown,
        lowers_top=lowers_top,
        top_tube_rear=_along(spec.bb, v, spec.seat_tube_length * 0.9),
        top_tube_front=_along(head_bottom, u, spec.head_tube_length * 0.8),
        down_tube_front=_along(head_bottom, u, spec.head_tube_length * 0.25),
        seat_stay_top=_along(spec.bb, v, spec.seat_tube_length * 0.82),
        stem_top=stem_top,
        grip=grip,
        lever_tip=_add(grip, (11.0, -4.5)),
        steer_axis=u,
    )


def pedal_position(spec: BikeSpec, crank_angle: float, far_side: bool = False) -> Point:
    """Pedal centre for a crank angle (0 = pedal at the top, increasing clockwise as seen
    from the drive side, i.e. the pedal moves forward over the top)."""
    angle = crank_angle + (math.pi if far_side else 0.0)
    return (
        spec.bb[0] + spec.crank_length * math.sin(angle),
        spec.bb[1] + spec.crank_length * math.cos(angle),
    )


def chain_lines(spec: BikeSpec) -> tuple[tuple[Point, Point], tuple[Point, Point]]:
    """Upper and lower chain runs: external tangents of chainring and rear cog."""
    (x1, y1), (x2, y2) = spec.bb, (0.0, 0.0)
    r1, r2 = spec.chainring_radius, spec.cog_radius
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    base = math.atan2(dy, dx)
    offset = math.acos((r1 - r2) / dist)
    runs = []
    for sign in (1.0, -1.0):
        a = base + sign * offset
        runs.append(
            (
                (x1 + r1 * math.cos(a), y1 + r1 * math.sin(a)),
                (x2 + r2 * math.cos(a), y2 + r2 * math.sin(a)),
            )
        )
    return runs[0], runs[1]


BIKES: dict[str, BikeSpec] = {"bmx": BikeSpec()}


def get_bike(name: str) -> BikeSpec:
    try:
        return BIKES[name]
    except KeyError:
        raise KeyError(f"unknown bike {name!r}; available: {', '.join(BIKES)}") from None
