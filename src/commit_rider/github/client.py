"""GitHub GraphQL client: authentication, bounded retries, error mapping.

The HTTP layer is a plain callable (``transport``) so tests never touch the network. The
default transport uses only the standard library (``urllib``), so the package needs no HTTP
dependency. The token lives only in the request header: it is never logged, never put in
an exception message and never stored on disk.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import random
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from commit_rider import __version__
from commit_rider.data.models import ContributionDay, ContributionSeries
from commit_rider.data.normalization import normalize_series
from commit_rider.data.validation import validate_username
from commit_rider.errors import (
    APIResponseError,
    AuthenticationError,
    ConfigError,
    GitHubError,
    MissingTokenError,
    NetworkError,
    RateLimitError,
    UserNotFoundError,
)
from commit_rider.github.graphql import (
    CONTRIBUTIONS_QUERY,
    GRAPHQL_ENDPOINT,
    build_variables,
    windows,
)
from commit_rider.github.parser import parse_calendar_response

log = logging.getLogger("commit_rider")
MAX_RETRY_AFTER = 60.0


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str], bytes, float], TransportResponse]


def urllib_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> TransportResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https enforced)
            return TransportResponse(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:  # noqa: BLE001
            payload = b""
        return TransportResponse(exc.code, {k.lower(): v for k, v in exc.headers.items()}, payload)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise NetworkError(f"Could not reach GitHub ({type(reason).__name__}: {reason})") from None


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        *,
        endpoint: str = GRAPHQL_ENDPOINT,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 16.0,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if not token or not token.strip():
            raise MissingTokenError(
                "GitHub's GraphQL API requires an access token, even for public data. "
                "Set GITHUB_TOKEN (or COMMIT_RIDER_TOKEN), or use --source demo for an offline preview."
            )
        if not endpoint.lower().startswith("https://"):
            raise ConfigError("The GitHub endpoint must use HTTPS")
        if timeout <= 0 or max_retries < 0:
            raise ConfigError("timeout must be positive and max_retries must not be negative")
        self._token = token.strip()
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._rng = rng or random.Random()

    def __repr__(self) -> str:  # never reveal the token
        return f"GitHubClient(endpoint={self.endpoint!r}, token=***)"

    # ------------------------------------------------------------------ HTTP -----
    def _backoff(self, attempt: int) -> float:
        delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
        return delay + self._rng.uniform(0, 0.25 * delay)

    def _post(self, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"commit-rider/{__version__}",
        }
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        last_error: GitHubError | None = None
        for attempt in range(self.max_retries + 1):
            wait: float | None = None
            try:
                response = self._transport(self.endpoint, headers, body, self.timeout)
                return self._interpret(response)
            except NetworkError as exc:
                last_error, wait = exc, self._backoff(attempt)
            except _Retry as retry:
                last_error = retry.error
                wait = retry.delay if retry.delay is not None else self._backoff(attempt)
            if attempt < self.max_retries:
                log.warning("GitHub request failed (%s); retrying in %.1fs (%d/%d)", last_error, wait, attempt + 1, self.max_retries)
                self._sleep(wait)
        assert last_error is not None
        raise last_error

    def _interpret(self, response: TransportResponse) -> Mapping[str, Any]:
        status = response.status
        text = response.body.decode("utf-8", errors="replace")
        if status == 401:
            raise AuthenticationError(
                "GitHub rejected the token (HTTP 401). Check that the secret is set, has not "
                "expired and was not revoked."
            )
        if status in (403, 429):
            remaining = response.headers.get("x-ratelimit-remaining")
            retry_after = _number(response.headers.get("retry-after"))
            lowered = text.lower()
            if status == 429 or remaining == "0" or "rate limit" in lowered or retry_after is not None:
                reset = _number(response.headers.get("x-ratelimit-reset"))
                reset_at = dt.datetime.fromtimestamp(reset, dt.timezone.utc) if reset else None
                error = RateLimitError(
                    "GitHub rate limit reached"
                    + (f"; it resets at {reset_at:%Y-%m-%d %H:%M} UTC" if reset_at else "")
                    + ". Try again later.",
                    reset_at,
                )
                if retry_after is not None and retry_after <= MAX_RETRY_AFTER:
                    raise _Retry(error, retry_after)
                raise error
            raise AuthenticationError(
                "GitHub refused the request (HTTP 403). The token lacks permission; see docs/installation.md."
            )
        if status >= 500:
            raise _Retry(NetworkError(f"GitHub is temporarily unavailable (HTTP {status})"))
        if status != 200:
            raise APIResponseError(f"Unexpected HTTP status {status} from GitHub")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise APIResponseError("GitHub returned a response that is not valid JSON") from None
        if not isinstance(payload, Mapping):
            raise APIResponseError("GitHub returned an unexpected JSON document")
        errors = payload.get("errors")
        if errors:
            self._raise_graphql_errors(errors)
        return payload

    @staticmethod
    def _raise_graphql_errors(errors: Any) -> None:
        items = errors if isinstance(errors, list) else [errors]
        types = {str(e.get("type", "")) for e in items if isinstance(e, Mapping)}
        messages = "; ".join(str(e.get("message", e)) for e in items[:3] if isinstance(e, Mapping))[:300]
        if "NOT_FOUND" in types:
            raise UserNotFoundError("GitHub reports that this user does not exist")
        if "RATE_LIMITED" in types:
            raise RateLimitError("GitHub GraphQL rate limit reached. Try again later.")
        if types & {"FORBIDDEN", "INSUFFICIENT_SCOPES"}:
            raise AuthenticationError(f"The token is not allowed to read this data: {messages}")
        raise APIResponseError(f"GitHub returned an error: {messages or 'unknown error'}")

    # ------------------------------------------------------------- public API -----
    def fetch_contributions(
        self, username: str, start: dt.date, end: dt.date, include_private: bool = False
    ) -> ContributionSeries:
        login = validate_username(username)
        if start > end:
            raise ConfigError(f"Start date {start} is after end date {end}")
        days: list[ContributionDay] = []
        reported = 0
        restricted: int | None = None
        canonical = login
        for first, last in windows(start, end):
            payload = self._post(CONTRIBUTIONS_QUERY, build_variables(login, first, last))
            window = parse_calendar_response(payload)
            canonical = window.login or canonical
            days.extend(d for d in window.days if first <= d.date <= last)
            reported += window.total
            if window.restricted is not None:
                restricted = (restricted or 0) + window.restricted
        series = normalize_series(
            days,
            start=start,
            end=end,
            source="github",
            username=canonical,
            reported_total=reported,
            restricted=restricted if include_private else None,
        )
        if series.filled_days:
            log.warning("GitHub returned no entry for %d day(s) in the range; they are shown as zero", series.filled_days)
        if series.total != reported:
            log.warning("Daily counts sum to %d but GitHub reports %d in total for this range", series.total, reported)
        return series


class _Retry(Exception):
    """Internal: a retryable failure, optionally with a server-requested delay."""

    def __init__(self, error: GitHubError, delay: float | None = None) -> None:
        super().__init__(str(error))
        self.error = error
        self.delay = delay


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None
