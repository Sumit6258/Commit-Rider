import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from commit_rider import __version__, cli
from commit_rider.errors import AuthenticationError, GitHubError
from commit_rider.rendering.exporter import ExportReport
from commit_rider.rendering.themes import THEMES
from tests.support import ROOT, demo

SMALL = ["--width", "320", "--height", "96", "--fps", "6", "--duration", "2"]
TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def run_cli(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    environment = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "COMMIT_RIDER_TOKEN", "GH_TOKEN")}
    environment.update(env or {})
    with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_help_version_and_listings(self):
        code, out, _ = run_cli("--help")
        self.assertEqual(code, 0)
        for needle in ("--username", "--source", "--input-json", "--theme", "exit codes", "COMMIT_RIDER_TOKEN"):
            self.assertIn(needle, out)
        self.assertNotIn("--token", cli.build_parser()._option_string_actions)  # secrets never go on the command line
        code, out, _ = run_cli("--version")
        self.assertEqual((code, out.strip()), (0, f"commit-rider {__version__}"))
        code, out, _ = run_cli("--list-themes")
        self.assertEqual(code, 0)
        for name in ("midnight", "forest", "sunset", "neon", "snow", "minimal", "monochrome"):
            self.assertIn(name, out)
        code, out, _ = run_cli("--print-schema")
        self.assertEqual(code, 0)
        self.assertIn("theme", json.loads(out))

    def test_usage_and_configuration_errors_exit_2(self):
        cases = [
            ([], "Choose a data source"),
            (["--username", "bad name!", "--output", "x.gif"], "not a valid GitHub username"),
            (["--source", "demo", "--theme", "nope"], "theme must be one of"),
            (["--source", "demo", "--width", "10"], "width must be"),
            (["--source", "demo", "--days", "3"], "days must be between"),
            (["--source", "demo", "--from", "2026-05-01", "--to", "2026-01-01"], "after the end date"),
            (["--source", "demo", "--bike-color", "red"], "bike_color"),
            (["--source", "nonsense"], ""),
            (["--source", "demo", "--from", "yesterday"], ""),
            (["--source", "json"], "--input-json is required"),
        ]
        for argv, message in cases:
            with self.subTest(argv=argv):
                code, _, err = run_cli(*argv)
                self.assertEqual(code, 2, err)
                self.assertIn(message, err)

    def test_missing_token_is_a_clear_exit_4(self):
        code, _, err = run_cli("--username", "octocat", "--output", str(self.dir / "x.gif"))
        self.assertEqual(code, 4)
        self.assertIn("GITHUB_TOKEN", err)
        self.assertIn("--source demo", err)

    def test_named_token_variable_is_used_and_secrets_are_redacted(self):
        class Boom:
            def __init__(self, token):
                self.token = token

            def fetch_contributions(self, *args, **kwargs):
                raise AuthenticationError(f"rejected {self.token} (HTTP 401)")

        with mock.patch("commit_rider.sources.GitHubClient", Boom):
            code, out, err = run_cli("--username", "octocat", "--token-env", "MY_PAT", env={"MY_PAT": TOKEN, "GITHUB_TOKEN": "other"})
        self.assertEqual(code, 4)
        self.assertNotIn(TOKEN, out + err)
        self.assertIn("***", err)

    def test_generation_errors_have_distinct_exit_codes(self):
        out_gif = str(self.dir / "o.gif")
        self.assertEqual(run_cli("--source", "demo", "--output", str(self.dir / "o.png"))[0], 5)
        self.assertEqual(run_cli("--source", "demo", "--output", str(self.dir))[0], 5)
        with mock.patch("os.access", return_value=False):
            code, _, err = run_cli("--source", "demo", "--output", out_gif)
        self.assertEqual(code, 5)
        self.assertIn("not writable", err)
        blocker = self.dir / "file"
        blocker.write_text("x")
        self.assertEqual(run_cli("--source", "demo", "--output", str(blocker / "sub" / "o.gif"))[0], 5)
        self.assertEqual(run_cli("--input-json", str(self.dir / "missing.json"), "--output", out_gif)[0], 3)
        bad = self.dir / "bad.json"
        bad.write_text("{oops")
        code, _, err = run_cli("--input-json", str(bad), "--output", out_gif)
        self.assertEqual(code, 3)
        self.assertIn("Invalid JSON", err)

    def test_demo_run_writes_gif_and_preview(self):
        gif = self.dir / "out" / "demo.gif"
        code, out, err = run_cli("--source", "demo", "--output", str(gif), *SMALL)
        self.assertEqual(code, 0, err)
        self.assertIn("synthetic", out + err)
        self.assertIn("loops forever", out)
        with Image.open(gif) as im:
            self.assertEqual((im.size, im.n_frames, im.info["loop"]), ((320, 96), 12, 0))
        with Image.open(gif.with_suffix(".png")) as png:
            self.assertEqual(png.size, (320, 96))

    def test_preview_options_and_quiet(self):
        gif = self.dir / "a.gif"
        code, out, err = run_cli("--source", "demo", "--output", str(gif), "--no-preview", "-q", *SMALL)
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertFalse(gif.with_suffix(".png").exists())
        custom = self.dir / "elsewhere" / "p.png"
        run_cli("--source", "demo", "--output", str(self.dir / "b.gif"), "--preview", str(custom), *SMALL)
        self.assertTrue(custom.exists())
        self.assertFalse((self.dir / "b.png").exists())

    def test_json_input_and_days(self):
        code, out, err = run_cli("--input-json", str(ROOT / "examples" / "sample-contributions.json"), "--days", "30",
                                 "--output", str(self.dir / "j.gif"), "--no-preview", *SMALL)
        self.assertEqual(code, 0, err)
        self.assertIn("30 days", out)

    def test_config_file_flags_override_and_theme_file(self):
        config = self.dir / "cfg.json"
        config.write_text(json.dumps({"theme": "snow", "width": 400, "ride-mode": "stunt", "particles": False}))
        captured = {}

        def fake_generate(series, settings, output, **kwargs):
            captured["settings"] = settings
            report = ExportReport(Path(output), 12, settings.width, settings.height, 2000, 0, 1000)
            from commit_rider.data.stats import compute_stats
            return mock.Mock(report=report, preview_path=None, stats=compute_stats(series), series=series,
                             summary={"jumps": 1, "flips": 0, "wheelies": 0}, seconds=0.1)

        with mock.patch("commit_rider.cli.generate", fake_generate):
            code, _, err = run_cli("--source", "demo", "--config", str(config), "--theme", "forest", "--width", "500", "-q")
            s = captured["settings"]
            self.assertEqual((code, s.theme, s.width, s.ride_mode, s.particles), (0, "forest", 500, "stunt", False), err)
            theme_file = self.dir / "theme.json"
            theme_file.write_text(json.dumps({"name": "cli-custom-theme", "jersey": "#123456"}))
            self.addCleanup(THEMES.pop, "cli-custom-theme", None)
            code, _, err = run_cli("--source", "demo", "--theme-file", str(theme_file), "-q")
            self.assertEqual((code, captured["settings"].theme), (0, "cli-custom-theme"), err)
            code, _, err = run_cli("--source", "demo", "--config", str(self.dir / "nope.json"), "-q")
            self.assertEqual(code, 2)
            config.write_text("[1, 2]")
            self.assertEqual(run_cli("--source", "demo", "--config", str(config), "-q")[0], 2)

    def test_interrupt_and_unexpected_errors(self):
        with mock.patch("commit_rider.cli.generate", side_effect=KeyboardInterrupt):
            self.assertEqual(run_cli("--source", "demo", "-q")[0], 130)
        with mock.patch("commit_rider.cli.generate", side_effect=RuntimeError("kaboom")):
            code, _, err = run_cli("--source", "demo", "-q")
        self.assertEqual(code, 1)
        self.assertIn("kaboom", err)  # a traceback is shown, not swallowed
        self.assertIn("unexpected internal error", err)

    def test_github_failures_use_exit_4(self):
        with mock.patch("commit_rider.cli.load_series", side_effect=GitHubError("down")):
            self.assertEqual(run_cli("--username", "octocat", "-q")[0], 4)


class SubprocessTests(unittest.TestCase):
    def test_python_dash_m_works_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.gif"
            proc = subprocess.run(
                [sys.executable, "-m", "commit_rider", "--source", "demo", "--output", str(out), *SMALL],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertGreater(out.stat().st_size, 1000)
            proc = subprocess.run([sys.executable, "-m", "commit_rider"], capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
