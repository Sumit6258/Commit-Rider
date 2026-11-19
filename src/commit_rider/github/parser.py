"""Validate and convert a GraphQL response into plain data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from commit_rider.data.models import ContributionDay
from commit_rider.data.validation import parse_count, parse_date
from commit_rider.errors import APIResponseError, DataError, UserNotFoundError


@dataclass(frozen=True)
class CalendarWindow:
    login: str
    days: list[ContributionDay]
    total: int
    restricted: int | None


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise APIResponseError(f"Unexpected GitHub response: {where} is missing or not an object")
    return value


def parse_calendar_response(payload: Any) -> CalendarWindow:
    root = _mapping(payload, "the response")
    data = _mapping(root.get("data"), "'data'")
    user = data.get("user")
    if user is None:
        raise UserNotFoundError("GitHub reports that this user does not exist")
    user = _mapping(user, "'data.user'")
    collection = _mapping(user.get("contributionsCollection"), "'contributionsCollection'")
    calendar = _mapping(collection.get("contributionCalendar"), "'contributionCalendar'")
    weeks = calendar.get("weeks")
    if not isinstance(weeks, list):
        raise APIResponseError("Unexpected GitHub response: 'weeks' is not a list")
    total = calendar.get("totalContributions")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise APIResponseError("Unexpected GitHub response: 'totalContributions' is not a count")

    days: list[ContributionDay] = []
    for week in weeks:
        week = _mapping(week, "a calendar week")
        entries = week.get("contributionDays")
        if not isinstance(entries, list):
            raise APIResponseError("Unexpected GitHub response: a week has no 'contributionDays'")
        for entry in entries:
            entry = _mapping(entry, "a contribution day")
            try:
                days.append(
                    ContributionDay(parse_date(entry.get("date")), parse_count(entry.get("contributionCount")))
                )
            except DataError as exc:
                raise APIResponseError(f"Unexpected GitHub response: {exc}") from None

    restricted = collection.get("restrictedContributionsCount")
    if restricted is not None and (isinstance(restricted, bool) or not isinstance(restricted, int) or restricted < 0):
        restricted = None
    login = user.get("login")
    return CalendarWindow(
        login=login if isinstance(login, str) else "",
        days=days,
        total=total,
        restricted=restricted,
    )
