"""Publish generated files to a git branch without touching anything else.

Used by the GitHub Action's optional ``publish-branch`` input. It only adds or updates the files
it was given (other files already on the branch are kept) and creates the branch as an orphan
(no shared history with your code) when it does not exist. All git commands are run with
argument lists (no shell).

History: a daily animation of several megabytes would grow a branch by gigabytes per year, so
the default (``squash``) keeps a single commit on the publish branch. It is replaced with
``--force-with-lease`` pinned to the commit that was just fetched, so a push from anybody else
in the meantime is never overwritten (the operation is retried from the new tip instead).
``keep`` appends a normal fast-forward commit instead.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from commit_rider.errors import PublishError
from commit_rider.logging_utils import redact

log = logging.getLogger("commit_rider")
_BRANCH = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,100}$")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@dataclass(frozen=True)
class PublishResult:
    branch: str
    changed: bool
    commit: str | None
    files: tuple[str, ...]


class _PushRejected(Exception):
    pass


class _Git:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=180
            )
        except FileNotFoundError:
            raise PublishError("git is not installed or not on PATH") from None
        except subprocess.TimeoutExpired:
            raise PublishError(f"git {args[0]} timed out") from None
        if check and proc.returncode != 0:
            raise PublishError(f"git {args[0]} failed: {redact((proc.stderr or proc.stdout).strip())[:400]}")
        return proc


def _validate(branch: str, subdir: str, files: Sequence[Path]) -> None:
    if not _BRANCH.match(branch) or branch.endswith(("/", ".lock")):
        raise PublishError(f"{branch!r} is not an acceptable branch name")
    if subdir:
        pure = PurePosixPath(subdir)
        if pure.is_absolute() or ".." in pure.parts:
            raise PublishError("publish-dir must be a relative path without '..'")
    if not files:
        raise PublishError("There are no files to publish")
    for f in files:
        if not Path(f).is_file():
            raise PublishError(f"Cannot publish {f}: file not found")


def publish_files(
    files: Sequence[str | os.PathLike[str]],
    *,
    branch: str,
    repo_dir: str | os.PathLike[str] = ".",
    message: str = "Update Commit Rider animation",
    subdir: str = "",
    remote: str = "origin",
    author_name: str = BOT_NAME,
    author_email: str = BOT_EMAIL,
    retries: int = 2,
    history: str = "squash",
) -> PublishResult:
    paths = [Path(f) for f in files]
    if history not in ("squash", "keep"):
        raise PublishError("history must be 'squash' or 'keep'")
    _validate(branch, subdir.strip("/"), paths)
    subdir = subdir.strip("/")
    repo = Path(repo_dir).resolve()
    git = _Git(repo)
    probe = git.run("rev-parse", "--git-dir", check=False)
    if probe.returncode != 0:
        raise PublishError("The working directory is not a git repository; run actions/checkout first")
    for attempt in range(retries + 1):
        try:
            return _attempt(git, paths, branch, subdir, message, remote, author_name, author_email, history)
        except _PushRejected:
            if attempt == retries:
                raise PublishError(
                    f"Could not push to '{branch}': the branch kept changing during {retries + 1} attempts"
                ) from None
            log.warning("Push to %s was rejected (branch moved); retrying", branch)
    raise AssertionError("unreachable")  # pragma: no cover


def _attempt(
    git: _Git, files: list[Path], branch: str, subdir: str, message: str, remote: str,
    name: str, email: str, history: str,
) -> PublishResult:
    tracking = f"refs/remotes/{remote}/{branch}"
    fetched = git.run("fetch", "--no-tags", "--depth=1", remote, f"+refs/heads/{branch}:{tracking}", check=False)
    exists = fetched.returncode == 0
    if not exists and "couldn't find remote ref" not in (fetched.stderr or "").lower():
        raise PublishError(f"git fetch failed: {redact((fetched.stderr or '').strip())[:400]}")
    old_tip = git.run("rev-parse", tracking).stdout.strip() if exists else None

    scratch = Path(tempfile.mkdtemp(prefix="commit-rider-publish-"))
    worktree = scratch / "wt"
    try:
        git.run("worktree", "add", "--detach", str(worktree), tracking if exists else "HEAD")
        wt = _Git(worktree)
        if not exists:  # a brand-new orphan branch must contain only our files
            wt.run("rm", "-rf", "--quiet", "--ignore-unmatch", ".")
            wt.run("clean", "-fdxq")
        dest = worktree / subdir if subdir else worktree
        dest.mkdir(parents=True, exist_ok=True)
        relative = []
        for source in files:
            shutil.copyfile(source, dest / source.name)
            relative.append((PurePosixPath(subdir) / source.name).as_posix() if subdir else source.name)
        wt.run("add", "--", *relative)
        if wt.run("diff", "--cached", "--quiet", check=False).returncode == 0 and exists:
            return PublishResult(branch, False, old_tip, tuple(relative))

        tree = wt.run("write-tree").stdout.strip()
        parents = ["-p", old_tip] if (exists and history == "keep" and old_tip) else []
        commit = wt.run(
            "-c", f"user.name={name}", "-c", f"user.email={email}",
            "commit-tree", tree, *parents, "-m", message,
        ).stdout.strip()
        push_args = ["push"]
        if exists and history == "squash":
            push_args.append(f"--force-with-lease=refs/heads/{branch}:{old_tip}")
        pushed = wt.run(*push_args, remote, f"{commit}:refs/heads/{branch}", check=False)
        if pushed.returncode != 0:
            err = (pushed.stderr or "").lower()
            raced = (
                "non-fast-forward" in err or "fetch first" in err or "stale info" in err
                or ("[rejected]" in err and "remote rejected" not in err)
            )
            if raced:  # somebody else pushed meanwhile: try again from the new tip
                raise _PushRejected
            raise PublishError(
                f"git push failed: {redact((pushed.stderr or '').strip())[:400]}. The workflow needs "
                "'permissions: contents: write' and actions/checkout must keep its credentials."
            )
        return PublishResult(branch, True, commit, tuple(relative))
    finally:
        git.run("worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(scratch, ignore_errors=True)
        git.run("worktree", "prune", check=False)
