"""The animation engine: plan a whole lap once, then evaluate any frame instantly.

``Timeline`` precomputes, on the terrain's spatial grid, everything that depends on where
the rider is (pose, posture, wheel spin, crank angle, camera height) together with the
mapping from grid position to time. ``Timeline.frame(k)`` is then a cheap, pure
interpolation, which makes frames independent of one another and the lap exactly
periodic: ``frame(frames)`` equals ``frame(0)`` shifted by one lap.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

from commit_rider.animation import camera as cam
from commit_rider.animation import movement
from commit_rider.animation.bicycle import BikeSpec, get_bike
from commit_rider.animation.cyclist import RiderControls
from commit_rider.animation.particles import Puff, landing_burst, takeoff_puffs, trail_puff
from commit_rider.animation.physics import GroundContact
from commit_rider.animation.stunts import StuntPlan, plan_stunts, rider_controls
from commit_rider.config.settings import Settings
from commit_rider.terrain.geometry import Terrain

CADENCE = {"normal": 1.7, "speed": 2.1, "stunt": 1.8, "relaxed": 1.4}
NO_FLY_MARGIN = 90.0


@dataclass(frozen=True)
class FrameState:
    index: int
    t: float
    x_mid: float
    rear: tuple[float, float]
    pitch: float
    wheel_angle: float
    wheel_step: float
    crank: float
    controls: RiderControls
    airborne: bool
    speed: float
    day_index: int | None
    ground_y: float
    air_height: float
    cam_x: float
    cam_y: float
    progress: float


def _lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def _lerp_angle(a: float, b: float, f: float) -> float:
    delta = (b - a + math.pi) % math.tau - math.pi
    return a + delta * f


class Timeline:
    def __init__(self, terrain: Terrain, settings: Settings) -> None:
        self.terrain = terrain
        self.settings = settings
        self.bike: BikeSpec = get_bike(settings.bike)
        self.fps = settings.fps
        self.frames = settings.frames
        self.duration = self.frames / self.fps
        self.n = terrain.n
        self.dx = terrain.dx
        self.period = terrain.period
        n, dx = self.n, self.dx
        spec = self.bike
        half_w = 0.5 * spec.wheelbase

        self.ground = GroundContact(terrain, spec.wheel_radius, spec.wheelbase)

        # The lap starts in the middle of the closing bridge: a calm, flat-ish valley where
        # the bicycle is always on the ground, so the seam of the loop is invisible.
        bridge_len = terrain.bridge_days * terrain.day_width
        shift = int(round(((terrain.data_length + bridge_len / 2) % self.period) / dx)) % n
        self.x_start = shift * dx
        g_mid = self.ground.mid_y[shift:] + self.ground.mid_y[:shift]
        g_pitch = self.ground.pitch[shift:] + self.ground.pitch[:shift]
        self.ground_mid_y, self.ground_pitch = g_mid, g_pitch

        data_len = terrain.data_length
        no_fly = []
        for i in range(n):
            x_world = ((i + shift) % n) * dx
            no_fly.append(x_world >= data_len - NO_FLY_MARGIN or x_world < NO_FLY_MARGIN)

        surface = [terrain.height(self.x_start + i * dx) for i in range(n)]
        self.plan: StuntPlan = plan_stunts(
            g_mid, g_pitch, dx, no_fly, settings.effective_stunts, surface=surface
        )
        flight_at: list = [None] * n
        for f in self.plan.flights:
            for i in range(f.start, f.end):
                flight_at[i] = f
        self.flight_at = flight_at
        wheelie_weight = [0.0] * n
        wheelie_delta = [0.0] * n
        for wh in self.plan.wheelies:
            for i in range(wh.start, wh.end + 1):
                w = wh.weight(i, dx)
                if w > wheelie_weight[i % n]:
                    wheelie_weight[i % n] = w
                    wheelie_delta[i % n] = wh.amplitude * w
        self.wheelie_weight = wheelie_weight

        # ---- final pose (rear wheel centre + pitch) per lap index -------------------------
        mid_y, theta, rear_x, rear_y = [], [], [], []
        for i in range(n):
            x_mid = self.x_start + i * dx
            f = flight_at[i]
            if f is not None:
                ym = f.mid_y(i, dx)
                th = f.pitch(i)
                rx = x_mid - half_w * math.cos(th)
                ry = ym - half_w * math.sin(th)
                fx = rx + spec.wheelbase * math.cos(th)
                fy = ry + spec.wheelbase * math.sin(th)
                lift = max(0.0, self.ground.penetration(rx, ry), self.ground.penetration(fx, fy))
                ym += lift
                ry += lift
            else:
                th_g = g_pitch[i]
                ym = g_mid[i]
                rx = x_mid - half_w * math.cos(th_g)
                ry = ym - half_w * math.sin(th_g)
                th = th_g + wheelie_delta[i]
            mid_y.append(ym)
            theta.append(th)
            rear_x.append(rx)
            rear_y.append(ry)
        self.mid_y, self.theta, self.rear_x, self.rear_y = mid_y, theta, rear_x, rear_y

        # ---- kinematics -----------------------------------------------------------------
        self.rel_speed = movement.speed_profile(g_pitch, dx)
        self.times = movement.integrate_time(self.rel_speed, dx, self.duration)
        self.wheel, self.wheel_total = movement.wheel_angles(
            rear_x, rear_y, self.period, spec.wheel_radius, spec.spokes
        )
        controls = rider_controls(g_pitch, self.plan, wheelie_weight, dx, self.period / self.frames)
        self.controls = controls
        self.crank, self.crank_total = movement.crank_angles(
            self.times,
            controls["climb"],
            controls["desc"],
            controls["level"],
            CADENCE[settings.ride_mode],
        )
        air_height = [max(0.0, mid_y[i] - g_mid[i]) for i in range(n)]
        self.cam_y = cam.camera_heights(terrain, self.x_start, n, dx, air_height)
        self.puffs: list[Puff] = self._build_puffs() if settings.particles else []

    # ----- particles -----------------------------------------------------------------
    def _speed_at(self, i: int) -> float:
        return self.dx / (self.times[i + 1] - self.times[i])

    def _build_puffs(self) -> list[Puff]:
        seed = self.settings.seed * 1009 + 5
        puffs: list[Puff] = []
        step = max(1, round(40.0 / self.dx))
        for i in range(0, self.n, step):
            if self.flight_at[i] is None:
                x = self.rear_x[i]
                puffs.append(
                    trail_puff(seed + i, self.times[i], x, self.terrain.height(x), self._speed_at(i))
                )
        for k, f in enumerate(self.plan.flights):
            x_take = self.x_start + f.start * self.dx
            puffs.extend(
                takeoff_puffs(
                    seed + 70000 + k,
                    self.times[f.start],
                    x_take,
                    self.terrain.height(x_take),
                    self._speed_at(f.start),
                )
            )
            x_land = self.x_start + f.end * self.dx
            end = min(f.end, self.n - 1)
            puffs.extend(
                landing_burst(
                    seed + 90000 + k,
                    self.times[end],
                    x_land,
                    self.terrain.height(x_land),
                    self._speed_at(end),
                    f.impact,
                )
            )
        return puffs

    # ----- frame evaluation ------------------------------------------------------------
    def _locate(self, t: float) -> tuple[int, float, int]:
        """Return (lap_index, fraction, whole_laps) for a time in seconds."""
        laps, tt = divmod(t, self.duration)
        i = bisect_right(self.times, tt) - 1
        i = min(max(i, 0), self.n - 1)
        span = self.times[i + 1] - self.times[i]
        return i, min(1.0, max(0.0, (tt - self.times[i]) / span)), int(laps)

    def frame(self, k: int) -> FrameState:
        t = k / self.fps
        i0, f, laps = self._locate(t)
        i1 = (i0 + 1) % self.n
        n = self.n
        offset = laps * self.period

        rear_x = _lerp(self.rear_x[i0], self.rear_x[i1] + (self.period if i1 == 0 else 0.0), f)
        rear_y = _lerp(self.rear_y[i0], self.rear_y[i1], f)
        x_mid = self.x_start + (i0 + f) * self.dx + offset
        dt = self.times[i0 + 1] - self.times[i0]
        c = self.controls
        controls = RiderControls(
            crank=_lerp(self.crank[i0], self.crank[i0 + 1], f) + laps * self.crank_total,
            stand=_lerp(c["stand"][i0], c["stand"][i1], f),
            climb=_lerp(c["climb"][i0], c["climb"][i1], f),
            desc=_lerp(c["desc"][i0], c["desc"][i1], f),
            compress=_lerp(c["compress"][i0], c["compress"][i1], f),
            air=_lerp(c["air"][i0], c["air"][i1], f),
            wheelie=_lerp(self.wheelie_weight[i0], self.wheelie_weight[i1], f),
        )
        mid_y = _lerp(self.mid_y[i0], self.mid_y[i1], f)
        ground_mid = _lerp(self.ground_mid_y[i0], self.ground_mid_y[i1], f)
        cam_x = cam.camera_x(x_mid, self.settings.view_width)
        return FrameState(
            index=k,
            t=t,
            x_mid=x_mid,
            rear=(rear_x + offset, rear_y),
            pitch=_lerp_angle(self.theta[i0], self.theta[i1], f),
            wheel_angle=_lerp(self.wheel[i0], self.wheel[i0 + 1], f) + laps * self.wheel_total,
            wheel_step=(self.wheel[i0 + 1] - self.wheel[i0]) / dt / self.fps,
            crank=controls.crank,
            controls=controls,
            airborne=self.flight_at[i0] is not None,
            speed=self.dx / dt,
            day_index=self.terrain.day_index_at(x_mid),
            ground_y=self.terrain.height(x_mid),
            air_height=max(0.0, mid_y - ground_mid),
            cam_x=cam_x,
            cam_y=_lerp(self.cam_y[i0], self.cam_y[i1], f),
            progress=(i0 + f) / n,
        )

    def summary(self) -> dict[str, float | int]:
        flights = self.plan.flights
        return {
            "frames": self.frames,
            "duration": self.duration,
            "jumps": len(flights),
            "flips": sum(f.flips for f in flights),
            "wheelies": len(self.plan.wheelies),
            "max_apex": max((f.apex for f in flights), default=0.0),
            "wheel_turns": self.wheel_total / math.tau,
            "pedal_turns": self.crank_total / math.tau,
        }
