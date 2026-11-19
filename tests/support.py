"""Shared helpers for the test suite."""

from __future__ import annotations

import datetime as dt
import functools
from pathlib import Path

from commit_rider.config.settings import Settings
from commit_rider.data.demo import generate_demo_series
from commit_rider.data.models import ContributionDay, ContributionSeries

ROOT = Path(__file__).resolve().parents[1]
# Small canvas so rendering tests stay fast; the physics/terrain are size-independent.
SMALL = {"width": 480, "height": 144, "fps": 10, "duration": 3.0}


def small_settings(**overrides) -> Settings:
    return Settings(**{**SMALL, **overrides})


@functools.lru_cache(maxsize=None)
def demo(days: int = 365) -> ContributionSeries:
    return generate_demo_series(days=days)


def series_from_counts(counts, start: dt.date = dt.date(2026, 1, 1)) -> ContributionSeries:
    days = tuple(ContributionDay(start + dt.timedelta(days=i), c) for i, c in enumerate(counts))
    return ContributionSeries(days=days, source="test")
