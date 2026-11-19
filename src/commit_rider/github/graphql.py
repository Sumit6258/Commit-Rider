"""The GraphQL query and date-window helpers.

Only aggregate contribution data is requested: per-day counts, the calendar total and the
aggregate count of contributions the viewer may not see per day. No repository names,
commit messages or other details are ever queried.
"""

from __future__ import annotations

import datetime as dt

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
# contributionsCollection spans at most one year per request; longer ranges are chunked.
MAX_WINDOW_DAYS = 365

CONTRIBUTIONS_QUERY = """
query CommitRiderContributions($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      hasAnyRestrictedContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
""".strip()


def windows(start: dt.date, end: dt.date, size: int = MAX_WINDOW_DAYS) -> list[tuple[dt.date, dt.date]]:
    """Split ``[start, end]`` (inclusive) into consecutive windows of at most ``size`` days."""
    if start > end:
        raise ValueError("start must not be after end")
    out = []
    cursor = start
    while cursor <= end:
        last = min(end, cursor + dt.timedelta(days=size - 1))
        out.append((cursor, last))
        cursor = last + dt.timedelta(days=1)
    return out


def build_variables(login: str, start: dt.date, end: dt.date) -> dict[str, str]:
    """UTC day boundaries: from 00:00:00Z on ``start`` to 23:59:59Z on ``end``."""
    return {
        "login": login,
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{end.isoformat()}T23:59:59Z",
    }
