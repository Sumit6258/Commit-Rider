"""Logging setup with secret redaction."""

from __future__ import annotations

import logging
import re
import sys

LOGGER_NAME = "commit_rider"
# GitHub token formats: classic (ghp_, gho_, ghu_, ghs_, ghr_) and fine-grained (github_pat_).
_TOKEN_PATTERN = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


class RedactingFilter(logging.Filter):
    """Replaces anything that looks like a GitHub token, and any explicitly registered
    secret, with ``***`` before a record is emitted."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add_secret(self, value: str | None) -> None:
        if value and len(value) >= 6:
            self._secrets.add(value)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return _TOKEN_PATTERN.sub("***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


REDACTOR = RedactingFilter()


def redact(text: str) -> str:
    """Redact secrets from arbitrary text (error messages, subprocess output)."""
    return REDACTOR.redact(text)


def register_secret(value: str | None) -> None:
    REDACTOR.add_secret(value)


def configure(verbosity: int = 0, quiet: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[commit-rider] %(levelname)s: %(message)s"))
    handler.addFilter(REDACTOR)
    logger.addHandler(handler)
    logger.propagate = False
    if quiet:
        logger.setLevel(logging.ERROR)
    else:
        logger.setLevel({0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG))
    return logger
