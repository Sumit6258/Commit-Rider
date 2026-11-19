"""Statistics shown in the optional overlay, computed only from retrieved data."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from commit_rider.data.models import ContributionSeries


@dataclass(frozen=True)
class ContributionStats:
    total: int
    days: int
    active_days: int
    max_count: int
    max_date: dt.date
    average: float
    current_streak: int
    longest_streak: int
    start: dt.date
    end: dt.date
    restricted: int | None


def compute_stats(series: ContributionSeries) -> ContributionStats:
    counts = series.counts
    max_count = max(counts)
    max_date = series.days[counts.index(max_count)].date

    longest = run = 0
    for count in counts:
        run = run + 1 if count > 0 else 0
        longest = max(longest, run)

    # Current streak: consecutive active days ending at the last day. A zero on the
    # very last day does not break it (the day may simply not be over yet).
    index = len(counts) - 1
    if counts[index] == 0:
        index -= 1
    current = 0
    while index >= 0 and counts[index] > 0:
        current += 1
        index -= 1

    return ContributionStats(
        total=sum(counts),
        days=len(counts),
        active_days=sum(1 for c in counts if c > 0),
        max_count=max_count,
        max_date=max_date,
        average=sum(counts) / len(counts),
        current_streak=current,
        longest_streak=longest,
        start=series.start,
        end=series.end,
        restricted=series.restricted,
    )
