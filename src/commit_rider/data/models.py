"""Plain data containers shared by every stage of the pipeline."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class ContributionDay:
    """Contributions made on one calendar day (UTC date)."""

    date: dt.date
    count: int


@dataclass(frozen=True)
class ContributionSeries:
    """A contiguous, chronological run of days.

    ``restricted`` is GitHub's *aggregate* count of contributions the viewer is not
    allowed to see per day (private repositories). It is never spread over days.
    """

    days: tuple[ContributionDay, ...]
    username: str | None = None
    source: str = "unknown"
    reported_total: int | None = None
    restricted: int | None = None
    filled_days: int = 0

    def __len__(self) -> int:
        return len(self.days)

    @property
    def counts(self) -> list[int]:
        return [day.count for day in self.days]

    @property
    def start(self) -> dt.date:
        return self.days[0].date

    @property
    def end(self) -> dt.date:
        return self.days[-1].date

    @property
    def total(self) -> int:
        return sum(day.count for day in self.days)
