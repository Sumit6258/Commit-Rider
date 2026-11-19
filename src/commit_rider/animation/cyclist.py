"""The rider rig: a posable skeleton with two-bone inverse kinematics.

The rider is attached to the bike at three places: the pelvis on the saddle (or standing
over the pedals), the hands on the grips and the feet on the pedals. Every frame the
hip target is chosen from the motion state (climbing, descending, airborne, landing...),
the torso lean is solved so the arms keep a natural bend, and the legs/arms follow by
IK, so the rider can never detach from the bicycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from commit_rider.animation.bicycle import BikePoints, BikeSpec, Point, pedal_position


@dataclass(frozen=True)
class RiderSpec:
    thigh: float = 40.0
    shin: float = 40.0
    torso: float = 44.0
    neck: float = 6.0
    head_radius: float = 11.5
    upper_arm: float = 28.0
    forearm: float = 27.0


@dataclass(frozen=True)
class RiderControls:
    crank: float = 0.0
    stand: float = 0.0  # 0 seated .. 1 standing on the pedals
    climb: float = 0.0  # 0..1 uphill intensity
    desc: float = 0.0  # 0..1 downhill intensity
    compress: float = 0.0  # -0.3 (extended) .. 1 (fully absorbed landing)
    air: float = 0.0  # 0..1 airborne weight
    wheelie: float = 0.0  # 0..1


@dataclass(frozen=True)
class Leg:
    hip: Point
    knee: Point
    ankle: Point
    heel: Point
    toe: Point
    ball: Point
    angle: float = 0.0


@dataclass(frozen=True)
class Arm:
    shoulder: Point
    elbow: Point
    hand: Point


@dataclass(frozen=True)
class RiderPose:
    hip: Point
    shoulder: Point
    head: Point
    head_angle: float
    torso_angle: float
    near_leg: Leg
    far_leg: Leg
    near_arm: Arm
    far_arm: Arm
    fork_compress: float
    max_stretch: float  # largest limb extension used (1.0 = fully straight); < 1 means reachable


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def two_bone_ik(
    root: Point, target: Point, l1: float, l2: float, bend: float
) -> tuple[Point, float]:
    """Return ``(joint, stretch)``. ``bend`` is +1 or -1 and picks which side the joint
    bows toward (+1: to the left of the root->target direction rotated counter-clockwise).
    ``stretch`` is the requested distance divided by the fully extended length."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    raw = math.hypot(dx, dy)
    if raw < 1e-9:
        return (root[0], root[1] - l1), 0.0
    ux, uy = dx / raw, dy / raw
    reach = _clamp(raw, abs(l1 - l2) + 1e-3, (l1 + l2) * 0.9995)
    a = (l1 * l1 - l2 * l2 + reach * reach) / (2.0 * reach)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    px, py = -uy, ux
    joint = (root[0] + ux * a + bend * px * h, root[1] + uy * a + bend * py * h)
    return joint, raw / (l1 + l2)


def _foot_points(pedal: Point, angle: float) -> tuple[Point, Point, Point]:
    """Ankle, heel and toe for a shoe whose ball rests on the pedal, tilted by ``angle``."""
    c, s = math.cos(angle), math.sin(angle)

    def place(dx: float, dy: float) -> Point:
        return (pedal[0] + dx * c - dy * s, pedal[1] + dx * s + dy * c)

    return place(-10.0, 9.5), place(-16.5, 1.5), place(8.5, 0.6)


SHOE_OUTLINE: tuple[Point, ...] = (
    (-16.5, -1.2), (-17.2, 5.4), (-12.8, 9.6), (-6.0, 10.6), (0.0, 7.2),
    (6.4, 4.6), (10.6, 2.0), (10.9, -0.9), (8.0, -2.6), (-14.0, -2.8),
)


def shoe_polygon(ball: Point, angle: float) -> list[Point]:
    """Shoe outline in bike-local coordinates for a foot whose ball is on ``ball``."""
    c, s = math.cos(angle), math.sin(angle)
    return [(ball[0] + x * c - y * s, ball[1] + x * s + y * c) for x, y in SHOE_OUTLINE]


def _solve_lean(hip: Point, grip: Point, torso: float, arm_dist: float) -> float:
    """Torso angle from vertical (radians, forward positive) so that the shoulder ends up
    ``arm_dist`` away from the grips; found by a scan plus bisection, so it is continuous."""

    def dist(alpha: float) -> float:
        sx = hip[0] + torso * math.sin(alpha)
        sy = hip[1] + torso * math.cos(alpha)
        return math.hypot(grip[0] - sx, grip[1] - sy)

    lo_a, hi_a = math.radians(-8.0), math.radians(78.0)
    step = math.radians(2.0)
    a = lo_a
    prev = dist(a)
    while a < hi_a:
        nxt = min(a + step, hi_a)
        d = dist(nxt)
        if d <= arm_dist <= prev or prev <= arm_dist <= d:
            lo, hi = a, nxt
            for _ in range(24):
                mid = 0.5 * (lo + hi)
                if (dist(mid) - arm_dist) * (dist(lo) - arm_dist) <= 0:
                    hi = mid
                else:
                    lo = mid
            return 0.5 * (lo + hi)
        a, prev = nxt, d
    # Unreachable target distance: take the closest lean we can.
    best, best_err = lo_a, abs(dist(lo_a) - arm_dist)
    a = lo_a
    while a <= hi_a:
        err = abs(dist(a) - arm_dist)
        if err < best_err:
            best, best_err = a, err
        a += step
    return best


def solve_pose(
    bike: BikeSpec, rider: RiderSpec, ctrl: RiderControls, points: BikePoints | None = None
) -> RiderPose:
    from commit_rider.animation.bicycle import bike_points

    fork_c = _clamp(0.9 * ctrl.compress, 0.0, 1.0) if ctrl.compress > 0 else 0.0
    pts = points or bike_points(bike, fork_c)

    stand = _ease(ctrl.stand)
    seated_hip = (pts.saddle_top[0] - 1.5, pts.saddle_top[1] + 7.0)
    standing_hip = (bike.bb[0] - 9.0, bike.bb[1] + 74.0)
    hip_x = _lerp(seated_hip[0], standing_hip[0], stand)
    hip_y = _lerp(seated_hip[1], standing_hip[1], stand)

    # Posture modifiers (all continuous in the controls).
    hip_x += 3.0 * ctrl.climb * (1.0 - stand) + 5.0 * ctrl.climb * stand
    hip_x -= 13.0 * ctrl.desc * stand + 4.0 * ctrl.air
    hip_y -= 5.0 * ctrl.desc * stand + 6.0 * ctrl.air
    hip_x -= 10.0 * ctrl.wheelie
    hip_y += 3.0 * ctrl.wheelie
    crouch = _clamp(ctrl.compress, -0.35, 1.0)
    hip_y -= 15.0 * crouch * (0.35 + 0.65 * stand)
    hip_x -= 3.0 * crouch

    # Feet: pedals follow the crank; the shoes stay roughly level.
    near_pedal = pedal_position(bike, ctrl.crank)
    far_pedal = pedal_position(bike, ctrl.crank, far_side=True)

    def foot_angle(crank: float) -> float:
        return (0.05 + 0.18 * math.cos(crank)) * (1.0 - 0.8 * ctrl.air)

    near_ankle, near_heel, near_toe = _foot_points(near_pedal, foot_angle(ctrl.crank))
    far_ankle, far_heel, far_toe = _foot_points(far_pedal, foot_angle(ctrl.crank + math.pi))

    # The hip bobs down if a foot at the bottom of the stroke would be out of reach.
    leg_max = (rider.thigh + rider.shin) * 0.975
    for ankle in (near_ankle, far_ankle):
        dx = hip_x - ankle[0]
        limit_y = ankle[1] + math.sqrt(max(leg_max * leg_max - dx * dx, 1.0))
        if hip_y > limit_y:
            hip_y = limit_y
    hip = (hip_x, hip_y)

    far_hip = (hip_x - 1.5, hip_y + 0.5)
    near_knee, s1 = two_bone_ik(hip, near_ankle, rider.thigh, rider.shin, +1.0)
    far_knee, s2 = two_bone_ik(far_hip, far_ankle, rider.thigh, rider.shin, +1.0)

    # Torso lean follows from how bent the arms should be.
    arm_dist = (
        47.0
        - 6.0 * ctrl.climb
        - 6.0 * _clamp(ctrl.compress, 0.0, 1.0)
        + 4.0 * ctrl.desc
        + 3.0 * stand
        + 6.0 * ctrl.wheelie
    )
    arm_dist = _clamp(arm_dist, 34.0, (rider.upper_arm + rider.forearm) * 0.97)
    grip = pts.grip
    lean = _solve_lean(hip, grip, rider.torso, arm_dist)
    shoulder = (hip[0] + rider.torso * math.sin(lean), hip[1] + rider.torso * math.cos(lean))
    head_angle = 0.45 * lean + 0.14
    head = (
        shoulder[0] + (rider.neck + rider.head_radius) * math.sin(head_angle),
        shoulder[1] + (rider.neck + rider.head_radius) * math.cos(head_angle),
    )

    far_shoulder = (shoulder[0] - 2.5, shoulder[1] + 1.0)
    far_grip = (grip[0] - 1.2, grip[1] + 0.8)
    near_elbow, s3 = two_bone_ik(shoulder, grip, rider.upper_arm, rider.forearm, -1.0)
    far_elbow, s4 = two_bone_ik(far_shoulder, far_grip, rider.upper_arm, rider.forearm, -1.0)

    return RiderPose(
        hip=hip,
        shoulder=shoulder,
        head=head,
        head_angle=head_angle,
        torso_angle=lean,
        near_leg=Leg(hip, near_knee, near_ankle, near_heel, near_toe, near_pedal, foot_angle(ctrl.crank)),
        far_leg=Leg(far_hip, far_knee, far_ankle, far_heel, far_toe, far_pedal, foot_angle(ctrl.crank + math.pi)),
        near_arm=Arm(shoulder, near_elbow, grip),
        far_arm=Arm(far_shoulder, far_elbow, far_grip),
        fork_compress=fork_c,
        max_stretch=max(s1, s2, s3, s4),
    )
