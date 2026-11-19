"""Turn a loose collection of days into a contiguous, chronological series."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from commit_rider.config.defaults import MAX_DAYS, MIN_DAYS
from commit_rider.data.models import ContributionDay, ContributionSeries
from commit_rider.errors import DataError


def normalize_series(
    days: Sequence[ContributionDay],
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    source: str = "unknown",
    username: str | None = None,
    reported_total: int | None = None,
    restricted: int | None = None,
) -> ContributionSeries:
    """Sort, de-duplicate check, clip to ``[start, end]`` and fill gaps with zero.

    Gaps are real "no contributions" days only when the input is complete, so the
    number of synthesised days is reported in ``filled_days`` for the caller to judge.
    """
    if not days:
        raise DataError("No contribution data was provided (the input is empty)")
    seen: dict[dt.date, int] = {}
    for day in days:
        if day.date in seen:
            raise DataError(f"Duplicate entry for {day.date.isoformat()}")
        if day.count < 0:
            raise DataError(f"Negative contribution count on {day.date.isoformat()}")
        seen[day.date] = day.count

    first = start or min(seen)
    last = end or max(seen)
    if first > last:
        raise DataError(f"Start date {first} is after end date {last}")
    length = (last - first).days + 1
    if length > MAX_DAYS:
        raise DataError(f"{length} days requested; the maximum is {MAX_DAYS}")
    if length < MIN_DAYS:
        raise DataError(f"{length} days of data is too short; at least {MIN_DAYS} days are required")

    out: list[ContributionDay] = []
    filled = 0
    for offset in range(length):
        day = first + dt.timedelta(days=offset)
        if day in seen:
            out.append(ContributionDay(day, seen[day]))
        else:
            out.append(ContributionDay(day, 0))
            filled += 1
    return ContributionSeries(
        days=tuple(out),
        username=username,
        source=source,
        reported_total=reported_total,
        restricted=restricted,
        filled_days=filled,
    )
