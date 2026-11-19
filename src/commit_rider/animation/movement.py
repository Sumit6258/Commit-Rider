"""Kinematics along the planned path: speed, time, wheel spin and pedalling.

All quantities are integrated over the lap's spatial grid and then scaled so that the
whole lap takes exactly the requested duration. Total wheel rotation and total crank
rotation are nudged (by well under 1%) to whole multiples of their visual symmetry so
the last frame lines up with the first: the loop has no rotation jump.
"""

from __future__ import annotations

import math

from commit_rider.terrain.interpolation import smooth_circular


def speed_profile(pitch: list[float], dx: float) -> list[float]:
    """Relative horizontal speed: slower uphill, faster downhill, smoothed over ~70 units."""
    pitch_s = smooth_circular(pitch, 30.0 / dx)
    raw = [min(1.28, max(0.72, 1.0 - 0.5 * math.sin(p))) for p in pitch_s]
    return smooth_circular(raw, 35.0 / dx)


def integrate_time(rel_speed: list[float], dx: float, duration: float) -> list[float]:
    """Cumulative real time (seconds) at each of ``n + 1`` lap indices; last equals duration."""
    cumulative = [0.0]
    for v in rel_speed:
        cumulative.append(cumulative[-1] + dx / v)
    scale = duration / cumulative[-1]
    return [t * scale for t in cumulative]


def wheel_angles(
    rear_x: list[float], rear_y: list[float], period: float, radius: float, spokes: int
) -> tuple[list[float], float]:
    """Wheel rotation (radians, clockwise positive) per lap index (``n + 1`` values).

    The wheel rolls without slipping, so rotation = path length / radius. The total is
    snapped to a whole number of spoke spacings so the loop closes seamlessly.
    """
    n = len(rear_x)
    arc = [0.0]
    for i in range(n):
        j = (i + 1) % n
        x_next = rear_x[j] + (period if j == 0 else 0.0)
        arc.append(arc[-1] + math.hypot(x_next - rear_x[i], rear_y[j] - rear_y[i]))
    spacing = math.tau / spokes
    raw_total = arc[-1] / radius
    snapped = max(1, round(raw_total / spacing)) * spacing
    factor = snapped / raw_total
    return [a / radius * factor for a in arc], snapped


LEVEL_RATE_CAP = 18.0  # rad/s: fastest the cranks swing to level in the air
LEVEL_GAIN = 14.0  # 1/s: how eagerly they settle (time constant about 0.07 s)


def _simulate_crank(
    times: list[float], climb: list[float], desc: list[float], level: list[float], cadence: float
) -> list[float]:
    angle = [0.0]
    cap = LEVEL_RATE_CAP
    for i in range(len(climb)):
        dt = times[i + 1] - times[i]
        pedal = math.tau * cadence * (1.0 - 0.25 * climb[i]) * (1.0 - 0.5 * desc[i])
        # Forward distance to the next "level pedals" angle (pi/2 or 3*pi/2).
        ahead = (math.pi / 2.0 - angle[-1]) % math.pi
        settle = cap * math.tanh(LEVEL_GAIN * ahead / cap)
        rate = (1.0 - level[i]) * pedal + level[i] * settle
        angle.append(angle[-1] + rate * dt)
    return angle


def crank_angles(
    times: list[float], climb: list[float], desc: list[float], level: list[float], cadence: float
) -> tuple[list[float], float]:
    """Crank angle per lap index (``n + 1`` values) and the total (a whole number of turns).

    Pedalling slows on steep climbs and descents (it never stops). While ``level`` is high
    (airborne) the cranks glide forward to the next level position (pedals horizontal) and
    stay there; they never run backwards.

    Loop closure: the total rotation must be a whole number of turns. Where the cranks end
    up depends on discrete choices made in flight ("which level position comes next"), so
    the total is not a continuous function of the cadence and cannot be tuned globally.
    Instead the (less than half a turn) difference is spread over the final stretch of the
    lap, after the last flight, which the planner keeps clear of jumps. No flight is
    disturbed and the correction is invisible.
    """
    n = len(climb)
    angle = _simulate_crank(times, climb, desc, level, cadence)
    last = max((i for i in range(n) if level[i] > 1e-3), default=-1)
    tail = min(n - 1, last + 1 + max(1, n // 400))
    tail_rotation = angle[n] - angle[tail]
    tail_time = times[n] - times[tail]
    turns = max(1, round(angle[n] / math.tau))
    correction = turns * math.tau - angle[n]
    while tail_rotation + correction < 0.3 * tail_rotation and correction < math.pi * 4:
        turns += 1  # never run the cranks backwards: add a turn instead
        correction += math.tau
    for i in range(tail, n + 1):
        angle[i] += correction * (times[i] - times[tail]) / tail_time
    return angle, turns * math.tau
