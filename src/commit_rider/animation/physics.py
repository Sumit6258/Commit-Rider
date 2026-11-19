"""Terrain-following physics: wheel contact and bicycle orientation.

A wheel of radius ``r`` rolling over a height field does not touch the ground directly
under its centre: it rests on the highest point of the terrain inside its circle. The
*offset curve* (centre height as a function of centre x) captures this exactly, so wheels
never penetrate the terrain, however sharp a feature is. For a rigid wheelbase ``W`` the
rear and front centres are then found so that both lie on the offset curve and are ``W``
apart; the bicycle's pitch is the direction between them.
"""

from __future__ import annotations

import math

from commit_rider.terrain.geometry import Terrain


class GroundContact:
    def __init__(self, terrain: Terrain, wheel_radius: float, wheelbase: float) -> None:
        self.terrain = terrain
        self.n = terrain.n
        self.dx = terrain.dx
        self.wheel_radius = wheel_radius
        self.wheelbase = wheelbase
        self.center_heights = self._offset_curve()
        self.mid_y, self.pitch = self._solve_all()

    def _offset_curve(self) -> list[float]:
        heights, n, dx, r = self.terrain.heights, self.n, self.dx, self.wheel_radius
        k = int(r / dx)
        profile = [math.sqrt(max(r * r - (j * dx) ** 2, 0.0)) for j in range(-k, k + 1)]
        out = []
        for i in range(n):
            best = -1e18
            for j in range(-k, k + 1):
                v = heights[(i + j) % n] + profile[j + k]
                if v > best:
                    best = v
            out.append(best)
        return out

    def center_y(self, x: float) -> float:
        """Height of a wheel centre resting on the terrain with its centre at ``x``."""
        u = (x % self.terrain.period) / self.dx
        i = int(u)
        if i >= self.n:
            i, u = 0, 0.0
        f = u - i
        c = self.center_heights
        return c[i] * (1.0 - f) + c[(i + 1) % self.n] * f

    def solve(self, x_mid: float) -> tuple[float, float]:
        """Both wheels on the ground, centred about ``x_mid``: returns (mid_y, pitch)."""
        w = self.wheelbase
        lo, hi = 0.25 * w, w  # horizontal separation of the two wheel centres

        def excess(sep: float) -> float:
            y_rear = self.center_y(x_mid - 0.5 * sep)
            y_front = self.center_y(x_mid + 0.5 * sep)
            return math.hypot(sep, y_front - y_rear) - w

        if excess(lo) >= 0.0:
            sep = lo
        else:
            for _ in range(28):
                mid = 0.5 * (lo + hi)
                if excess(mid) < 0.0:
                    lo = mid
                else:
                    hi = mid
            sep = 0.5 * (lo + hi)
        y_rear = self.center_y(x_mid - 0.5 * sep)
        y_front = self.center_y(x_mid + 0.5 * sep)
        return 0.5 * (y_rear + y_front), math.atan2(y_front - y_rear, sep)

    def _solve_all(self) -> tuple[list[float], list[float]]:
        mids, pitches = [], []
        for i in range(self.n):
            mid_y, pitch = self.solve(i * self.dx)
            mids.append(mid_y)
            pitches.append(pitch)
        return mids, pitches

    def penetration(self, x_center: float, y_center: float) -> float:
        """How far (>0) a wheel centre at (x, y) is below the offset curve."""
        return self.center_y(x_center) - y_center
