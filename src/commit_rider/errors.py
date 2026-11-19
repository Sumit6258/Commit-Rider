"""Exception hierarchy.

Every failure that is expected to reach a user derives from :class:`CommitRiderError`
and carries the process exit code the CLI should use.
"""

from __future__ import annotations

from datetime import datetime


class CommitRiderError(Exception):
    """Base class for all expected errors."""

    exit_code = 1


class ConfigError(CommitRiderError):
    """Invalid configuration or command-line usage."""

    exit_code = 2


class DataError(CommitRiderError):
    """Contribution data is missing, malformed or inconsistent."""

    exit_code = 3


class GitHubError(CommitRiderError):
    """Any failure while talking to the GitHub API."""

    exit_code = 4


class AuthenticationError(GitHubError):
    """The token was rejected or lacks permission."""


class MissingTokenError(AuthenticationError):
    """No token was supplied although the GraphQL API requires one."""


class UserNotFoundError(GitHubError):
    """The requested GitHub username does not exist."""


class RateLimitError(GitHubError):
    """GitHub rate limit reached."""

    def __init__(self, message: str, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class NetworkError(GitHubError):
    """Connection failure or timeout (after bounded retries)."""


class APIResponseError(GitHubError):
    """GitHub answered, but not with something we can use."""


class RenderError(CommitRiderError):
    """Rendering failed."""

    exit_code = 5


class OutputError(CommitRiderError):
    """The output file could not be written or failed validation."""

    exit_code = 5


class PublishError(CommitRiderError):
    """Publishing the generated files to a git branch failed."""

    exit_code = 6
