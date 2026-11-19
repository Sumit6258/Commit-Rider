"""Dust and spray particles.

Particles are pure functions of time: each puff has a spawn time and a deterministic
trajectory, so a frame can be rendered independently of all others and the loop stays
seamless (a puff that is still alive when the lap ends is simply continued in the next).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Puff:
    t0: float  # spawn time within the lap (seconds)
    x: float  # world x at spawn (lap coordinates, i.e. unwrapped within [x_start, x_start+period))
    y: float
    vx: float  # world units per second
    vy: float
    size0: float
    size1: float
    life: float
    alpha: float

    def at(self, t: float, duration: float, period: float) -> tuple[float, float, float, float] | None:
        """Position (x, y), radius and alpha at lap time ``t``, or None if not alive."""
        age = t - self.t0
        x_offset = 0.0
        if age < 0:  # spawned during the previous lap
            age += duration
            x_offset = -period
        if age < 0 or age >= self.life:
            return None
        k = age / self.life
        drag = 1.0 - math.exp(-3.0 * age)
        x = self.x + x_offset + self.vx * drag / 3.0
        y = self.y + self.vy * drag / 3.0 - 6.0 * age * age
        radius = self.size0 + (self.size1 - self.size0) * math.sqrt(k)
        return x, y, radius, self.alpha * (1.0 - k) ** 1.4


def landing_burst(
    seed: int, t0: float, x: float, y: float, speed: float, strength: float
) -> list[Puff]:
    rng = random.Random(seed)
    count = 6 + round(6 * strength)
    puffs = []
    for _ in range(count):
        direction = rng.choice((-1.0, 1.0))
        puffs.append(
            Puff(
                t0=t0 + rng.random() * 0.03,
                x=x + rng.uniform(-14, 14),
                y=y + 1.0,
                vx=direction * rng.uniform(25, 90) * (0.5 + strength) + 0.25 * speed,
                vy=rng.uniform(25, 85) * (0.6 + 0.6 * strength),
                size0=rng.uniform(3.0, 5.0),
                size1=rng.uniform(8.0, 13.0) * (0.7 + 0.5 * strength),
                life=rng.uniform(0.55, 0.9),
                alpha=rng.uniform(0.45, 0.7),
            )
        )
    return puffs


def trail_puff(seed: int, t0: float, x: float, y: float, speed: float) -> Puff:
    rng = random.Random(seed)
    return Puff(
        t0=t0,
        x=x + rng.uniform(-3, 3),
        y=y + 1.0,
        vx=-0.18 * speed * rng.uniform(0.6, 1.2),
        vy=rng.uniform(10, 32),
        size0=rng.uniform(1.8, 2.8),
        size1=rng.uniform(5.0, 8.0),
        life=rng.uniform(0.38, 0.55),
        alpha=rng.uniform(0.28, 0.42),
    )


def takeoff_puffs(seed: int, t0: float, x: float, y: float, speed: float) -> list[Puff]:
    rng = random.Random(seed)
    return [
        Puff(
            t0=t0 + i * 0.01,
            x=x + rng.uniform(-6, 6),
            y=y + 1.0,
            vx=-0.3 * speed * rng.uniform(0.5, 1.0),
            vy=rng.uniform(25, 60),
            size0=2.5,
            size1=rng.uniform(7, 10),
            life=rng.uniform(0.45, 0.65),
            alpha=0.55,
        )
        for i in range(4)
    ]
