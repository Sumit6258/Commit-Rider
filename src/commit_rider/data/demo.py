"""Deterministic synthetic contribution data for demos, tests and offline use.

The generated numbers are *not* anyone's real activity. They imitate a typical
developer: busy weekdays, quiet weekends, project bursts, a holiday and a few spikes.
"""

from __future__ import annotations

import datetime as dt
import math
import random

from commit_rider.data.models import ContributionDay, ContributionSeries

DEMO_END = dt.date(2026, 11, 14)
_WEEKDAY_BASE = (6.5, 7.0, 6.0, 6.5, 5.0, 1.6, 1.0)  # Monday .. Sunday


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= limit:
            return k - 1


def generate_demo_series(
    days: int = 365, end: dt.date = DEMO_END, seed: int = 7
) -> ContributionSeries:
    rng = random.Random(seed)
    start = end - dt.timedelta(days=days - 1)
    phases = [rng.random() * math.tau for _ in range(3)]
    vacations = [
        (int(days * 0.30) + rng.randint(-8, 8), rng.randint(8, 13)),
        (int(days * 0.72) + rng.randint(-8, 8), rng.randint(5, 9)),
    ]
    out: list[ContributionDay] = []
    for i in range(days):
        date = start + dt.timedelta(days=i)
        mood = (
            0.95
            + 0.55 * math.sin(math.tau * i / 67 + phases[0])
            + 0.30 * math.sin(math.tau * i / 19 + phases[1])
            + 0.20 * math.sin(math.tau * i / 7.5 + phases[2])
        )
        count = _poisson(rng, _WEEKDAY_BASE[date.weekday()] * max(mood, 0.05))
        if rng.random() < 0.03:
            count += rng.randint(14, 46)  # a burst or a spike day
        if any(v0 <= i < v0 + length for v0, length in vacations) and rng.random() < 0.92:
            count = 0
        out.append(ContributionDay(date, count))
    return ContributionSeries(days=tuple(out), username="demo", source="demo")
