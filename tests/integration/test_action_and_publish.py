import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commit_rider import action
from commit_rider.errors import PublishError
from commit_rider.publish import BOT_EMAIL, BOT_NAME, publish_files

TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SMALL = {"INPUT_WIDTH": "320", "INPUT_HEIGHT": "96", "INPUT_FPS": "6", "INPUT_DURATION": "2", "INPUT_SOURCE": "demo"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def run_action(env):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = action.main(env)
    return code, out.getvalue()


class ActionEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env = {**SMALL, "INPUT_OUTPUT": str(self.dir / "o" / "ride.gif"),
                    "GITHUB_OUTPUT": str(self.dir / "gh_output"), "GITHUB_STEP_SUMMARY": str(self.dir / "summary.md")}

    def test_helpers(self):
        self.assertEqual(action.env_name("ride-mode"), "INPUT_RIDE_MODE")
        self.assertEqual([action._truthy(v) for v in ("true", "YES", "1", "false", "off", "")], [True, True, True, False, False, False])
        self.assertTrue(action._truthy("", default=True))
        self.assertEqual(action._escape("a%b\nc\r"), "a%25b%0Ac%0D")

    def test_successful_run_writes_outputs_and_summary(self):
        code, out = run_action({**self.env, "INPUT_DAYS": "60"})
        self.assertEqual(code, 0, out)
        gif = Path(self.env["INPUT_OUTPUT"])
        self.assertTrue(gif.exists() and gif.with_suffix(".png").exists())
        written = dict(line.split("=", 1) for line in (self.dir / "gh_output").read_text().splitlines())
        self.assertEqual(set(written), {"path", "preview-path", "total-contributions", "frames", "size-bytes", "published"})
        self.assertEqual((written["frames"], written["published"], written["path"]), ("12", "false", str(gif)))
        self.assertEqual(int(written["size-bytes"]), gif.stat().st_size)
        self.assertGreater(int(written["total-contributions"]), 0)
        self.assertIn("Commit Rider", (self.dir / "summary.md").read_text())

    def test_preview_can_be_disabled(self):
        code, _ = run_action({**self.env, "INPUT_PREVIEW": "false"})
        self.assertEqual(code, 0)
        self.assertFalse(Path(self.env["INPUT_OUTPUT"]).with_suffix(".png").exists())

    def test_token_is_masked_and_never_printed_again(self):
        code, out = run_action({**self.env, "INPUT_TOKEN": TOKEN})
        self.assertEqual(code, 0)
        self.assertIn(f"::add-mask::{TOKEN}", out)
        self.assertEqual(out.count(TOKEN), 1)  # only inside the mask command

    def test_errors_become_workflow_annotations_with_exit_codes(self):
        code, out = run_action({**self.env, "INPUT_THEME": "nope", "INPUT_WIDTH": "5"})
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("::error title=Commit Rider::"))
        self.assertNotIn("\n  - ", out)  # multi-line messages are escaped (%0A) for the annotation
        self.assertIn("%0A", out)
        code, out = run_action({**self.env, "INPUT_SOURCE": "github"})  # no username anywhere
        self.assertEqual(code, 2)
        self.assertIn("username is required", out)
        code, out = run_action({**self.env, "INPUT_SOURCE": "github", "INPUT_USERNAME": "octocat"})  # no token
        self.assertEqual(code, 4)
        self.assertIn("::error", out)
        code, out = run_action({**self.env, "INPUT_DAYS": "many"})
        self.assertEqual(code, 2)
        self.assertIn("whole number", out)
        self.assertEqual(run_action({**self.env, "INPUT_INCLUDE_PRIVATE": "perhaps"})[0], 2)

    def test_username_defaults_to_the_repository_owner(self):
        seen = {}

        def fake_load(request, today=None):
            seen["request"] = request
            from tests.support import demo
            return demo(30)

        env = {**self.env, "INPUT_SOURCE": "github", "INPUT_TOKEN": "tok-123456", "GITHUB_REPOSITORY_OWNER": "Sumit6258"}
        with mock.patch("commit_rider.action.load_series", fake_load):
            code, _ = run_action(env)
        self.assertEqual(code, 0)
        self.assertEqual((seen["request"].username, seen["request"].token, seen["request"].source), ("Sumit6258", "tok-123456", "github"))

    def test_unexpected_failures_are_reported_not_hidden(self):
        with mock.patch("commit_rider.action.generate", side_effect=RuntimeError("kaboom")):
            code, out = run_action(self.env)
        self.assertEqual(code, 1)
        self.assertIn("::error", out)


class GitFixture(unittest.TestCase):
    """A bare 'origin' repository plus a clone, both local."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin.git"
        git(self.root, "init", "--bare", "--quiet", "--initial-branch=main", str(self.origin))
        self.work = self.root / "work"
        git(self.root, "clone", "--quiet", str(self.origin), str(self.work))
        git(self.work, "config", "user.name", "Dev")
        git(self.work, "config", "user.email", "dev@example.com")
        (self.work / "README.md").write_text("# my profile\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "--quiet", "-m", "init")
        git(self.work, "push", "--quiet", "origin", "HEAD:main")
        self.out = self.root / "dist"
        self.out.mkdir()
        self.gif = self.out / "commit-rider.gif"
        self.png = self.out / "commit-rider.png"
        self.gif.write_bytes(b"GIF89a-one")
        self.png.write_bytes(b"png-one")

    def remote(self, *args):
        return git(self.origin, *args)

    def tree(self, branch):
        return sorted(self.remote("ls-tree", "-r", "--name-only", branch).splitlines())


class PublishTests(GitFixture):
    def test_creates_an_orphan_branch_with_only_the_generated_files(self):
        result = publish_files([self.gif, self.png], branch="output", repo_dir=self.work)
        self.assertTrue(result.changed)
        self.assertEqual(self.tree("output"), ["commit-rider.gif", "commit-rider.png"])
        self.assertEqual(self.remote("rev-list", "--count", "output"), "1")
        self.assertEqual(self.remote("log", "-1", "--format=%P", "output"), "")  # orphan: no parent
        self.assertEqual(self.remote("log", "-1", "--format=%an <%ae>", "output"), f"{BOT_NAME} <{BOT_EMAIL}>")
        self.assertEqual(self.tree("main"), ["README.md"])  # the code branch is untouched
        # the local clone is left exactly as it was: no stray worktrees or branches
        self.assertEqual(git(self.work, "status", "--porcelain"), "")
        self.assertEqual(len(git(self.work, "worktree", "list").splitlines()), 1)
        self.assertEqual(git(self.work, "branch", "--list"), "* main")

    def test_unchanged_files_do_not_create_commits(self):
        publish_files([self.gif], branch="output", repo_dir=self.work)
        again = publish_files([self.gif], branch="output", repo_dir=self.work)
        self.assertFalse(again.changed)
        self.assertEqual(self.remote("rev-list", "--count", "output"), "1")

    def test_keep_history_adds_normal_fast_forward_commits(self):
        publish_files([self.gif, self.png], branch="output", repo_dir=self.work, message="first", history="keep")
        self.gif.write_bytes(b"GIF89a-two")
        result = publish_files([self.gif, self.png], branch="output", repo_dir=self.work, message="second", history="keep")
        self.assertTrue(result.changed)
        self.assertEqual(self.remote("rev-list", "--count", "output"), "2")
        self.assertEqual(self.remote("log", "-1", "--format=%s", "output"), "second")
        self.assertEqual(self.remote("show", "output:commit-rider.gif"), "GIF89a-two")
        self.assertEqual(self.remote("show", "output:commit-rider.png"), "png-one")

    def test_default_squash_keeps_a_single_commit_so_the_repository_does_not_bloat(self):
        for n in range(4):
            self.gif.write_bytes(f"GIF89a-{n}".encode())
            publish_files([self.gif, self.png], branch="output", repo_dir=self.work, message=f"update {n}")
        self.assertEqual(self.remote("rev-list", "--count", "output"), "1")
        self.assertEqual(self.remote("log", "-1", "--format=%s", "output"), "update 3")
        self.assertEqual(self.remote("show", "output:commit-rider.gif"), "GIF89a-3")
        self.assertEqual(self.remote("log", "-1", "--format=%P", "output"), "")

    def test_squash_keeps_unrelated_files_and_never_overwrites_a_concurrent_push(self):
        from commit_rider import publish as module
        publish_files([self.gif], branch="output", repo_dir=self.work)
        other = self.root / "other"
        git(self.root, "clone", "--quiet", "--branch", "output", str(self.origin), str(other))
        git(other, "config", "user.name", "Dev")
        git(other, "config", "user.email", "dev@example.com")
        real_run = module._Git.run
        raced = []

        def racing_run(self_, *args, **kwargs):
            if args and args[0] == "push" and not raced:  # somebody else pushes just before us
                raced.append(1)
                (other / "theirs.txt").write_text("their work")
                git(other, "add", ".")
                git(other, "commit", "--quiet", "-m", "theirs")
                git(other, "push", "--quiet", "origin", "HEAD:output")
            return real_run(self_, *args, **kwargs)

        self.gif.write_bytes(b"GIF89a-new")
        with mock.patch.object(module._Git, "run", racing_run):
            result = publish_files([self.gif], branch="output", repo_dir=self.work)
        self.assertTrue(result.changed)
        self.assertEqual(raced, [1])  # the lease refused the first push; the retry started from the new tip
        self.assertEqual(self.tree("output"), ["commit-rider.gif", "theirs.txt"])  # their file survived
        self.assertEqual(self.remote("show", "output:commit-rider.gif"), "GIF89a-new")

    def test_other_files_on_the_branch_are_preserved(self):
        publish_files([self.gif], branch="output", repo_dir=self.work)
        other = self.root / "other"
        git(self.root, "clone", "--quiet", "--branch", "output", str(self.origin), str(other))
        git(other, "config", "user.name", "Dev")
        git(other, "config", "user.email", "dev@example.com")
        (other / "notes.txt").write_text("keep me")
        git(other, "add", ".")
        git(other, "commit", "--quiet", "-m", "notes")
        git(other, "push", "--quiet", "origin", "HEAD:output")
        self.gif.write_bytes(b"GIF89a-three")
        for history in ("squash", "keep"):
            self.gif.write_bytes(f"GIF89a-{history}".encode())
            publish_files([self.gif], branch="output", repo_dir=self.work, history=history)
            self.assertEqual(self.tree("output"), ["commit-rider.gif", "notes.txt"], history)
        self.assertEqual(self.remote("show", "output:notes.txt"), "keep me")

    def test_subdirectory_publishing(self):
        publish_files([self.gif], branch="output", repo_dir=self.work, subdir="/assets/anim/")
        self.assertEqual(self.tree("output"), ["assets/anim/commit-rider.gif"])

    def test_races_are_retried_and_eventually_reported(self):
        from commit_rider import publish as module
        calls = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise module._PushRejected
            return module.PublishResult("output", True, "abc", ("f",))

        with mock.patch.object(module, "_attempt", flaky):
            self.assertTrue(publish_files([self.gif], branch="output", repo_dir=self.work).changed)
        self.assertEqual(len(calls), 3)
        with mock.patch.object(module, "_attempt", side_effect=module._PushRejected):
            with self.assertRaises(PublishError) as ctx:
                publish_files([self.gif], branch="output", repo_dir=self.work, retries=1)
        self.assertIn("kept changing", str(ctx.exception))

    def test_server_side_refusal_is_a_publish_error_with_a_hint(self):
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(PublishError) as ctx:
            publish_files([self.gif], branch="output", repo_dir=self.work)
        self.assertIn("contents: write", str(ctx.exception))
        self.assertNotIn("kept changing", str(ctx.exception))
        self.assertEqual(git(self.work, "worktree", "list").count("\n"), 0)  # cleaned up after failing

    def test_validation(self):
        for branch in ("", "-x", "a..b", "with space", "x.lock", "a//b", "feature/", "semi;colon", "$(id)"):
            with self.subTest(branch=branch), self.assertRaises(PublishError):
                publish_files([self.gif], branch=branch, repo_dir=self.work)
        for subdir in ("../up", "a/../../b"):
            with self.subTest(subdir=subdir), self.assertRaises(PublishError):
                publish_files([self.gif], branch="output", repo_dir=self.work, subdir=subdir)
        with self.assertRaises(PublishError):
            publish_files([self.gif], branch="output", repo_dir=self.work, history="rewrite")
        with self.assertRaises(PublishError):
            publish_files([], branch="output", repo_dir=self.work)
        with self.assertRaises(PublishError):
            publish_files([self.root / "missing.gif"], branch="output", repo_dir=self.work)
        with self.assertRaises(PublishError) as ctx:
            publish_files([self.gif], branch="output", repo_dir=self.root / "dist")  # not a git repository
        self.assertIn("actions/checkout", str(ctx.exception))
        git(self.work, "remote", "remove", "origin")
        with self.assertRaises(PublishError):
            publish_files([self.gif], branch="output", repo_dir=self.work)

    def test_the_action_can_publish_end_to_end(self):
        env = {**SMALL, "INPUT_OUTPUT": "dist/commit-rider.gif", "INPUT_PUBLISH_BRANCH": "output",
               "INPUT_COMMIT_MESSAGE": "refresh", "GITHUB_OUTPUT": str(self.root / "gh_out")}
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        code, out = run_action(env)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tree("output"), ["commit-rider.gif", "commit-rider.png"])
        self.assertEqual(self.remote("log", "-1", "--format=%s", "output"), "refresh")
        self.assertIn("published=true", (self.root / "gh_out").read_text())
        # the generated files in the workspace are not committed to the checked-out branch
        self.assertEqual(self.remote("ls-tree", "-r", "--name-only", "main"), "README.md")


if __name__ == "__main__":
    unittest.main()
