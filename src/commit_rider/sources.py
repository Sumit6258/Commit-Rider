"""Turn a data request (GitHub, demo data or a JSON file) into a ContributionSeries."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from commit_rider.config import defaults as d
from commit_rider.data.demo import DEMO_END, generate_demo_series
from commit_rider.data.models import ContributionSeries
from commit_rider.data.normalization import normalize_series
from commit_rider.data.validation import parse_contribution_json, validate_username
from commit_rider.errors import ConfigError, DataError
from commit_rider.github.client import GitHubClient

SOURCES = ("github", "demo", "json")
TOKEN_ENV_VARS = ("COMMIT_RIDER_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")


@dataclass(frozen=True)
class DataRequest:
    source: str = "github"
    username: str | None = None
    token: str | None = None
    input_json: Path | None = None
    days: int | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    include_private: bool = False


def resolve_token(env: Mapping[str, str], names: tuple[str, ...] = TOKEN_ENV_VARS) -> str | None:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def resolve_range(request: DataRequest, today: dt.date, default_end: dt.date | None = None) -> tuple[dt.date, dt.date]:
    end = request.end or default_end or today
    if request.start is not None:
        start = request.start
    else:
        days = request.days if request.days is not None else d.DEFAULT_DAYS
        if not d.MIN_DAYS <= days <= d.MAX_DAYS:
            raise ConfigError(f"days must be between {d.MIN_DAYS} and {d.MAX_DAYS}, got {days}")
        start = end - dt.timedelta(days=days - 1)
    if start > end:
        raise ConfigError(f"The start date {start} is after the end date {end}")
    length = (end - start).days + 1
    if not d.MIN_DAYS <= length <= d.MAX_DAYS:
        raise ConfigError(f"The date range covers {length} days; it must be {d.MIN_DAYS} to {d.MAX_DAYS}")
    return start, end


def load_series(
    request: DataRequest, *, today: dt.date | None = None, client: GitHubClient | None = None
) -> ContributionSeries:
    if request.source not in SOURCES:
        raise ConfigError(f"source must be one of {', '.join(SOURCES)}")
    today = today or today_utc()

    if request.source == "demo":
        start, end = resolve_range(request, today, default_end=DEMO_END)
        return generate_demo_series(days=(end - start).days + 1, end=end)

    if request.source == "json":
        if request.input_json is None:
            raise ConfigError("--input-json is required when the source is 'json'")
        try:
            text = Path(request.input_json).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DataError(f"Cannot read {request.input_json}: {exc}") from None
        days = parse_contribution_json(text)
        if request.start or request.end:
            return normalize_series(days, start=request.start, end=request.end, source="json")
        series = normalize_series(days, source="json")
        if request.days is not None and request.days < len(series):
            if request.days < d.MIN_DAYS:
                raise ConfigError(f"days must be at least {d.MIN_DAYS}")
            series = normalize_series(list(series.days[-request.days :]), source="json")
        return series

    # GitHub
    if not request.username:
        raise ConfigError("A GitHub username is required (--username). Use --source demo for sample data.")
    username = validate_username(request.username)
    start, end = resolve_range(request, today)
    if client is None:
        client = GitHubClient(request.token)
    return client.fetch_contributions(username, start, end, include_private=request.include_private)
