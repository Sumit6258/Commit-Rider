import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from commit_rider.errors import OutputError
from commit_rider.pipeline import check_output_path, generate
from commit_rider.rendering.exporter import validate_gif
from tests.support import demo, series_from_counts, small_settings

TINY = {"width": 320, "height": 96, "fps": 6, "duration": 2.0}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_full_pipeline_produces_a_validated_gif_and_preview(self):
        progress = []
        result = generate(demo(), small_settings(**TINY), self.dir / "sub" / "ride.gif", progress=lambda a, b: progress.append((a, b)))
        report = result.report
        self.assertEqual((report.frames, report.width, report.height, report.loop), (12, 320, 96, 0))
        self.assertAlmostEqual(report.duration_ms, 2000, delta=20)
        self.assertEqual(progress[0], (1, 12))
        self.assertEqual(progress[-1], (12, 12))
        self.assertEqual(result.preview_path, self.dir / "sub" / "ride.png")
        with Image.open(result.preview_path) as png:
            self.assertEqual(png.size, (320, 96))
        self.assertEqual(result.stats.total, demo().total)
        self.assertGreaterEqual(result.summary["jumps"], 0)

    def test_output_is_byte_for_byte_reproducible(self):
        a = generate(demo(), small_settings(**TINY), self.dir / "a.gif", preview=False)
        b = generate(demo(), small_settings(**TINY), self.dir / "b.gif", preview=False)
        self.assertEqual(a.report.path.read_bytes(), b.report.path.read_bytes())
        c = generate(demo(), small_settings(**TINY, seed=5), self.dir / "c.gif", preview=False)
        self.assertNotEqual(a.report.path.read_bytes(), c.report.path.read_bytes())

    def test_edge_case_series_all_produce_valid_looping_gifs(self):
        spike = [0] * 40
        spike[20] = 4000
        cases = {
            "no contributions": series_from_counts([0] * 30),
            "one active day": series_from_counts([0] * 14 + [9] + [0] * 15),
            "identical counts": series_from_counts([5] * 30),
            "extreme spike": series_from_counts(spike),
            "minimum length": series_from_counts([1, 4, 0, 9, 2, 0, 3]),
            "leap day": series_from_counts([2, 7, 1, 0, 5, 3, 8, 0, 2, 6, 1, 1, 4, 9], start=dt.date(2028, 2, 24)),
            "long zero run": series_from_counts([6] * 5 + [0] * 80 + [6] * 5),
        }
        for name, series in cases.items():
            with self.subTest(case=name):
                path = self.dir / f"{name.replace(' ', '_')}.gif"
                result = generate(series, small_settings(**TINY), path, preview=False)
                self.assertEqual((result.report.frames, result.report.loop), (12, 0))
                validate_gif(path, expected_size=(320, 96), expected_frames=12, expected_fps=6)

    def test_longest_supported_range(self):
        from commit_rider.data.demo import generate_demo_series
        series = generate_demo_series(days=1100)
        result = generate(series, small_settings(**TINY), self.dir / "long.gif", preview=False)
        self.assertEqual(result.stats.days, 1100)

    def test_size_limit_falls_back_and_reports_honestly(self):
        with self.assertLogs("commit_rider", level="WARNING"):
            result = generate(demo(), small_settings(width=640, height=192, fps=10, duration=3.0, max_size_mb=0.2), self.dir / "big.gif", preview=False)
        self.assertFalse(result.report.within_limit)
        self.assertGreater(len(result.report.attempts), 1)
        validate_gif(result.report.path)  # the smallest attempt is still a valid animation

    def test_statistics_overlay_through_the_pipeline(self):
        result = generate(demo(), small_settings(**TINY, show_stats=True), self.dir / "stats.gif", preview=False)
        self.assertTrue(result.report.path.exists())

    def test_output_path_checks(self):
        self.assertEqual(check_output_path(self.dir / "x" / "y.GIF"), self.dir / "x" / "y.GIF")
        self.assertTrue((self.dir / "x").is_dir())
        for bad in (self.dir / "x.png", self.dir, self.dir / "noext"):
            with self.subTest(bad=bad), self.assertRaises(OutputError):
                check_output_path(bad)
        (self.dir / "f").write_text("x")
        with self.assertRaises(OutputError):
            check_output_path(self.dir / "f" / "o.gif")
        with mock.patch("os.access", return_value=False), self.assertRaises(OutputError):
            check_output_path(self.dir / "ro" / "o.gif")

    def test_failure_to_write_leaves_no_partial_file(self):
        target = self.dir / "w.gif"
        with mock.patch("pathlib.Path.write_bytes", side_effect=PermissionError("denied")):
            with self.assertRaises(OutputError):
                generate(demo(), small_settings(**TINY), target, preview=False)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
