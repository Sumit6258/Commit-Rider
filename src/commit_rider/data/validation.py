"""Validation and parsing of untrusted contribution input."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from commit_rider.data.models import ContributionDay
from commit_rider.errors import ConfigError, DataError

# GitHub logins: letters, digits and hyphens (enterprise-managed logins also use "_").
_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,37}[A-Za-z0-9])?$")


def validate_username(value: str) -> str:
    if not isinstance(value, str) or not _USERNAME.match(value.strip()):
        raise ConfigError(
            f"{value!r} is not a valid GitHub username "
            "(1-39 characters: letters, digits, hyphens; no leading or trailing hyphen)"
        )
    return value.strip()


def parse_date(value: Any) -> dt.date:
    """Parse ``YYYY-MM-DD`` (an ISO timestamp is accepted; only its date part is used)."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise DataError(f"Invalid date {value!r}: expected a YYYY-MM-DD string")
    text = value.strip()[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise DataError(f"Invalid date {value!r}: expected a real calendar date (YYYY-MM-DD)") from None


def parse_count(value: Any, where: str = "count") -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataError(f"Invalid {where} {value!r}: expected a non-negative whole number")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")) or not value.is_integer():
            raise DataError(f"Invalid {where} {value!r}: expected a non-negative whole number")
        value = int(value)
    if value < 0:
        raise DataError(f"Invalid {where} {value!r}: contribution counts cannot be negative")
    return value


def days_from_records(records: Iterable[Mapping[str, Any]]) -> list[ContributionDay]:
    """Convert ``{"date": ..., "count": ...}`` records (or GitHub's raw field names)."""
    days: list[ContributionDay] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise DataError(f"Entry #{index} is not an object: {record!r}")
        if "date" not in record:
            raise DataError(f"Entry #{index} has no 'date' field")
        count_key = next((k for k in ("count", "contributionCount") if k in record), None)
        if count_key is None:
            raise DataError(f"Entry #{index} ({record.get('date')!r}) has no 'count' field")
        days.append(
            ContributionDay(parse_date(record["date"]), parse_count(record[count_key], count_key))
        )
    return days


def _days_from_calendar(calendar: Mapping[str, Any]) -> list[ContributionDay]:
    weeks = calendar.get("weeks")
    if not isinstance(weeks, list):
        raise DataError("Calendar object has no 'weeks' list")
    records: list[Mapping[str, Any]] = []
    for week in weeks:
        if not isinstance(week, Mapping) or not isinstance(week.get("contributionDays"), list):
            raise DataError("Calendar week without a 'contributionDays' list")
        records.extend(week["contributionDays"])
    return days_from_records(records)


def parse_contribution_json(text: str) -> list[ContributionDay]:
    """Parse the JSON formats documented in docs/configuration.md.

    Accepted: a list of records, ``{"days": [...]}``, ``{"contributions": [...]}``, a bare
    GitHub ``contributionCalendar`` object, or a complete GraphQL response.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataError(f"Invalid JSON: {exc}") from None
    if isinstance(payload, list):
        return days_from_records(payload)
    if isinstance(payload, Mapping):
        for key in ("days", "contributions"):
            if isinstance(payload.get(key), list):
                return days_from_records(payload[key])
        node: Any = payload
        for key in ("data", "user", "contributionsCollection", "contributionCalendar"):
            if isinstance(node, Mapping) and key in node:
                node = node[key]
        if isinstance(node, Mapping) and "weeks" in node:
            return _days_from_calendar(node)
    raise DataError(
        "Unrecognised JSON layout. Expected a list of {\"date\", \"count\"} objects, "
        "an object with a \"days\" list, or a GitHub contributionCalendar."
    )
