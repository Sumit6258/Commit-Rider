"""Stunt planning: jumps, wheelies, flips and the rider's preparation for them.

Nothing here is random in the "unstable" sense. A jump is planned from the terrain:
a *lip* is a place where a steep climb abruptly levels off or drops away. From the lip
the bicycle follows a true parabola until it meets the ground again, and its pitch eases
from the launch slope to the landing slope, so it always lands wheels-down on the slope.
Wheelies are placed on long, flat stretches. Intensity (0..1) decides how eager the
planner is; 0 disables everything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from commit_rider.terrain.interpolation import limit_rate, smooth_circular, smoothstep


MAX_CHANGE_PER_FRAME = 0.45  # no posture control may change by more than this between frames


@dataclass(frozen=True)
class Flight:
    start: int  # last grounded lap index (take-off)
    end: int  # first grounded lap index (touch-down)
    y0: float
    slope0: float
    gravity: float
    pitch0: float
    pitch1: float
    flips: int
    impact: float
    apex: float

    def mid_y(self, index: float, dx: float) -> float:
        d = (index - self.start) * dx
        return self.y0 + self.slope0 * d - 0.5 * self.gravity * d * d

    def progress(self, index: float) -> float:
        return (index - self.start) / (self.end - self.start)

    def pitch(self, index: float) -> float:
        u = min(1.0, max(0.0, self.progress(index)))
        e = smoothstep((u - 0.08) / 0.84)
        return self.pitch0 + (self.pitch1 - self.pitch0 + math.tau * self.flips) * e


@dataclass(frozen=True)
class Wheelie:
    start: int
    end: int
    amplitude: float

    def weight(self, index: int, dx: float) -> float:
        if index < self.start or index > self.end:
            return 0.0
        ramp = 0.3 * (self.end - self.start)
        return min(smoothstep((index - self.start) / ramp), smoothstep((self.end - index) / ramp))


@dataclass
class StuntPlan:
    flights: list[Flight] = field(default_factory=list)
    wheelies: list[Wheelie] = field(default_factory=list)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


# The rider's head centre relative to the bicycle's midpoint (bike-local units): it is the part
# that hangs lowest when the bicycle is upside down.
HEAD_OFFSET = (6.0, 128.0)
HEAD_CLEARANCE = 11.5 + 8.0  # head radius plus a visible gap


def _head_clears_ground(f: Flight, surface: list[float], dx: float) -> bool:
    """Would the rider's head stay clear of the *terrain surface* for the whole flight?"""
    n = len(surface)
    for i in range(f.start, f.end + 1, 2):
        theta = f.pitch(i)
        c, s = math.cos(theta), math.sin(theta)
        head_x = c * HEAD_OFFSET[0] - s * HEAD_OFFSET[1]
        head_y = f.mid_y(i, dx) + s * HEAD_OFFSET[0] + c * HEAD_OFFSET[1]
        j = min(n - 1, max(0, round(i + head_x / dx)))
        if head_y - HEAD_CLEARANCE < surface[j]:
            return False
    return True


def plan_stunts(
    mid_y: list[float],
    pitch: list[float],
    dx: float,
    no_fly: list[bool],
    intensity: float,
    gravity: float | None = None,
    surface: list[float] | None = None,
) -> StuntPlan:
    plan = StuntPlan()
    n = len(mid_y)
    if intensity <= 0.0:
        return plan
    intensity = min(1.0, intensity)
    gravity = gravity if gravity is not None else 0.0036 - 0.0006 * intensity

    w = max(2, round(4.0 / dx))
    slope = [(mid_y[(i + w) % n] - mid_y[(i - w) % n]) / (2 * w * dx) for i in range(n)]
    lip_slope_min = 0.34 - 0.14 * intensity
    lip_drop_min = 0.58 - 0.24 * intensity
    a, b = round(8.0 / dx), round(42.0 / dx)

    candidates: list[tuple[float, int, float]] = []
    for i in range(n):
        if no_fly[i]:
            continue
        before = _mean([slope[(i - k) % n] for k in range(a, b)])
        if before < lip_slope_min:
            continue
        after = _mean([slope[(i + k) % n] for k in range(a, b)])
        if before - after >= lip_drop_min:
            candidates.append((before - after, i, before))
    candidates.sort(reverse=True)

    min_gap = round((430.0 - 150.0 * intensity) / dx)
    flips_left = 2 if intensity >= 0.75 else 0
    taken: list[Flight] = []

    def simulate(i: int, slope0: float) -> tuple[int, float] | None:
        """Landing index and highest clearance of the parabola launched at ``i``, if valid."""
        y0 = mid_y[i]
        best_clear = 0.0
        for d in range(1, round(1000.0 / dx)):
            j = i + d
            if j >= n - round(30.0 / dx):
                return None
            x = d * dx
            clear = y0 + slope0 * x - 0.5 * gravity * x * x - mid_y[j]
            if d < 8 and clear < -0.3:
                return None
            best_clear = max(best_clear, clear)
            if d >= 8 and clear <= 0.0:
                return j, best_clear
        return None

    def make_flight(i: int, landing: int, slope0: float, clear: float, flips: int) -> Flight:
        x_land = (landing - i) * dx
        impact = min(1.0, max(0.15, (slope[landing] - (slope0 - gravity * x_land)) / 0.8))
        return Flight(i, landing, mid_y[i], slope0, gravity, pitch[i], pitch[landing], flips, impact, clear)

    for score, i, before in candidates:
        if any(i < f.end + min_gap and f.start - min_gap < i for f in taken):
            continue
        slope0 = min(0.95, max(0.18, before * 0.9))
        sim = simulate(i, slope0)
        if sim is None or (sim[0] - i) * dx < 140.0 or sim[1] < 7.0:
            continue
        flight = make_flight(i, sim[0], slope0, sim[1], 0)
        if flips_left:
            # A backflip needs time in the air and, above all, room for the rider's head:
            # try a bigger pop off the lip, and keep the flip only if nothing touches the ground.
            for pop in (0.0, 0.16, 0.30, 0.45, 0.60):
                boosted = simulate(i, min(1.25, slope0 + pop))
                if boosted is None or (boosted[0] - i) * dx < 280.0 or boosted[1] < 50.0:
                    continue
                candidate = make_flight(i, boosted[0], min(1.25, slope0 + pop), boosted[1], 1)
                if surface is not None and _head_clears_ground(candidate, surface, dx):
                    flight, flips_left = candidate, flips_left - 1
                    break
        taken.append(flight)
    plan.flights = sorted(taken, key=lambda f: f.start)

    # ---- wheelies on long flat stretches -------------------------------------------------
    count = round(3 * intensity)
    if count > 0:
        smooth_pitch = smooth_circular(pitch, 20.0 / dx)
        blocked = [False] * n
        for f in plan.flights:
            for k in range(f.start - round(50 / dx), f.end + round(50 / dx)):
                blocked[k % n] = True
        ok = [abs(smooth_pitch[i]) < 0.24 and not no_fly[i] and not blocked[i] for i in range(n)]
        runs: list[tuple[int, int]] = []
        i = 0
        while i < n:
            if ok[i]:
                j = i
                while j < n and ok[j]:
                    j += 1
                runs.append((j - i, i))
                i = j
            else:
                i += 1
        need = round(240.0 / dx)
        for length, start in sorted(runs, reverse=True):
            if len(plan.wheelies) >= count:
                break
            if length >= need:
                mid = start + length // 2
                half = round(120.0 / dx)
                plan.wheelies.append(Wheelie(mid - half, mid + half, 0.40))
        plan.wheelies.sort(key=lambda wh: wh.start)
    return plan


def rider_controls(
    pitch: list[float],
    plan: StuntPlan,
    wheel_weight: list[float],
    dx: float,
    frame_step: float = 37.0,
) -> dict[str, list[float]]:
    """Per-lap-index posture parameters for the rider rig (all periodic and smooth).

    ``frame_step`` is the average distance (world units) the rider travels per frame; it
    converts the per-frame change limit into a per-unit-distance rate limit.
    """
    n = len(pitch)
    pitch_s = smooth_circular(pitch, 25.0 / dx)
    climb = [min(1.0, max(0.0, (p - 0.12) / 0.30)) for p in pitch_s]
    desc = [min(1.0, max(0.0, (-p - 0.14) / 0.28)) for p in pitch_s]

    air = [0.0] * n
    pre = [0.0] * n
    compress = [0.0] * n
    for f in plan.flights:
        for i in range(f.start, f.end):
            air[i % n] = 1.0
        lead = round(80.0 / dx)
        for k in range(lead):
            idx = (f.start - k) % n
            pre[idx] = max(pre[idx], smoothstep(1.0 - k / lead))
        # Pre-load crouch, pop extension, then landing absorption (smooth impulse response).
        for k in range(-round(60 / dx), 0):
            t = (k + round(60 / dx)) / round(60 / dx)
            compress[(f.start + k) % n] += 0.38 * math.sin(math.pi * t)
        for k in range(-round(20 / dx), round(20 / dx)):
            t = (k + round(20 / dx)) / round(40 / dx)
            compress[(f.start + k) % n] -= 0.25 * math.sin(math.pi * t)
        peak = 135.0
        for k in range(round(700 / dx)):
            s = k * dx / peak
            compress[(f.end + k) % n] += f.impact * (s * math.exp(1.0 - s)) ** 2
    # Pedals level out for the whole flight (a little before take-off, a little after the
    # landing). Unlike the posture controls this is not rate-limited: cranks can swing fast.
    level = [0.0] * n
    for f in plan.flights:
        for i in range(f.start - round(25 / dx), f.end + round(12 / dx)):
            level[i % n] = 1.0
    level = smooth_circular(level, 5.0 / dx)
    air = smooth_circular(air, 14.0 / dx)

    # Mild suspension work on terrain curvature: compress in valleys, extend over crests.
    span = round(35.0 / dx)
    for i in range(n):
        curvature = (pitch[(i + span) % n] - pitch[(i - span) % n]) / (2 * span * dx)
        compress[i] += min(0.5, max(-0.25, curvature * 90.0))
    compress = smooth_circular(compress, 6.0 / dx)

    stand_raw = [
        max(0.85 * climb[i], 0.6 * desc[i], air[i], 0.8 * pre[i], 0.55 * wheel_weight[i])
        for i in range(n)
    ]
    stand = smooth_circular(stand_raw, 20.0 / dx)
    # The rider can move quickly, but never pop: bound the change per *frame*, whatever
    # the frame rate, duration or speed (those only change how far a frame travels).
    step = MAX_CHANGE_PER_FRAME * dx / max(frame_step, dx)
    return {
        "stand": [min(1.0, max(0.0, v)) for v in limit_rate(stand, step)],
        "climb": limit_rate(climb, step),
        "desc": limit_rate(desc, step),
        "air": [min(1.0, max(0.0, v)) for v in limit_rate(air, step)],
        "level": [min(1.0, max(0.0, v)) for v in level],
        "compress": [min(1.0, max(-0.35, v)) for v in limit_rate(compress, step)],
    }
