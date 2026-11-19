"""Entry point used by the composite GitHub Action (``python -m commit_rider.action``).

The action passes its inputs as ``INPUT_*`` environment variables (never interpolated
into a shell command), so untrusted input values cannot inject commands.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import traceback
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from commit_rider.config.settings import Settings
from commit_rider.errors import CommitRiderError, ConfigError
from commit_rider.logging_utils import configure, redact, register_secret
from commit_rider.pipeline import generate
from commit_rider.publish import publish_files
from commit_rider.rendering.themes import load_theme_file
from commit_rider.sources import DataRequest, load_series

log = logging.getLogger("commit_rider")

SETTING_INPUTS = (
    "theme", "bike", "width", "height", "fps", "duration", "ride-mode", "terrain-mode", "speed",
    "height-sensitivity", "smoothing", "stunt-intensity", "particles", "show-stats", "quality",
    "max-size-mb", "seed", "scaling", "bike-color", "rider-color", "terrain-color", "background-color",
)
OTHER_INPUTS = (
    "username", "token", "source", "output", "preview", "days", "include-private", "theme-file",
    "publish-branch", "publish-dir", "publish-history", "commit-message",
)
ALL_INPUTS = SETTING_INPUTS + OTHER_INPUTS


def env_name(input_name: str) -> str:
    return "INPUT_" + input_name.upper().replace("-", "_")


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _truthy(value: str, default: bool = False) -> bool:
    text = value.strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Expected true or false, got {value!r}")


def _write_outputs(env: Mapping[str, str], values: Mapping[str, str]) -> None:
    target = env.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _write_summary(env: Mapping[str, str], lines: list[str]) -> None:
    target = env.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def run(env: Mapping[str, str] | MutableMapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    configure(verbosity=1 if env.get("RUNNER_DEBUG") == "1" or env.get("ACTIONS_STEP_DEBUG") == "true" else 0)
    value = {name: env.get(env_name(name), "").strip() for name in ALL_INPUTS}

    token = value["token"] or env.get("GITHUB_TOKEN", "").strip() or None
    if token:
        register_secret(token)
        print(f"::add-mask::{token}")

    if value["theme-file"]:
        load_theme_file(value["theme-file"])
    settings = Settings.from_mapping({name: value[name] for name in SETTING_INPUTS})

    source = value["source"] or "github"
    username = value["username"] or env.get("GITHUB_REPOSITORY_OWNER", "").strip() or None
    try:
        days = int(value["days"]) if value["days"] else None
    except ValueError:
        raise ConfigError(f"days must be a whole number, got {value['days']!r}") from None
    request = DataRequest(
        source=source, username=username, token=token, days=days,
        include_private=_truthy(value["include-private"]),
    )
    series = load_series(request, today=dt.datetime.now(dt.timezone.utc).date())

    output = Path(value["output"] or "dist/commit-rider.gif")
    want_preview = _truthy(value["preview"], default=True)
    result = generate(series, settings, output, preview=want_preview)

    outputs = {
        "path": str(result.report.path),
        "preview-path": str(result.preview_path) if result.preview_path else "",
        "total-contributions": str(result.stats.total),
        "frames": str(result.report.frames),
        "size-bytes": str(result.report.size_bytes),
        "published": "false",
    }
    print(
        f"Generated {result.report.path} ({result.report.size_mb:.2f} MiB, {result.report.frames} frames, "
        f"{result.stats.total:,} contributions, {result.stats.start} to {result.stats.end})"
    )

    if value["publish-branch"]:
        files = [result.report.path] + ([result.preview_path] if result.preview_path else [])
        published = publish_files(
            files, branch=value["publish-branch"], repo_dir=Path.cwd(),
            message=value["commit-message"] or "Update Commit Rider animation",
            subdir=value["publish-dir"],
            history=value["publish-history"] or "squash",
        )
        outputs["published"] = "true" if published.changed else "false"
        print(
            f"Published to branch '{published.branch}'" + (f" ({published.commit[:7]})" if published.commit else "")
            if published.changed else f"Branch '{published.branch}' already contains this animation; nothing to commit"
        )

    _write_outputs(env, outputs)
    _write_summary(env, [
        "### Commit Rider",
        "",
        f"- Contributions: **{result.stats.total:,}** ({result.stats.start} to {result.stats.end})",
        f"- Animation: `{result.report.path}` ({result.report.size_mb:.2f} MiB, {result.report.frames} frames)",
        f"- Source: {source}" + (" (synthetic demo data)" if source == "demo" else ""),
    ])
    return 0


def main(env: Mapping[str, str] | None = None) -> int:
    try:
        return run(env)
    except CommitRiderError as exc:
        print(f"::error title=Commit Rider::{_escape(redact(str(exc)))}")
        return exc.exit_code
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("::error title=Commit Rider::Unexpected internal error; see the log for the traceback")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
