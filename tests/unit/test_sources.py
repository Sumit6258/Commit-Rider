import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from commit_rider.config import defaults as d
from commit_rider.data.models import ContributionSeries
from commit_rider.errors import ConfigError, DataError, MissingTokenError
from commit_rider.sources import DataRequest, load_series, resolve_range, resolve_token
from tests.support import ROOT, demo

TODAY = dt.date(2026, 11, 14)


class FakeClient:
    def __init__(self):
        self.calls = []

    def fetch_contributions(self, username, start, end, include_private=False):
        self.calls.append((username, start, end, include_private))
        return ContributionSeries(days=demo().days[:10], username=username, source="github")


class TokenTests(unittest.TestCase):
    def test_resolution_order_and_blank_values(self):
        env = {"GITHUB_TOKEN": "b", "COMMIT_RIDER_TOKEN": "a", "GH_TOKEN": "c"}
        self.assertEqual(resolve_token(env), "a")
        self.assertEqual(resolve_token({"GITHUB_TOKEN": "  ", "GH_TOKEN": "c"}), "c")
        self.assertIsNone(resolve_token({}))
        self.assertEqual(resolve_token({"MY_TOKEN": "z"}, ("MY_TOKEN",)), "z")


class RangeTests(unittest.TestCase):
    def test_default_is_the_last_365_days_ending_today(self):
        start, end = resolve_range(DataRequest(), TODAY)
        self.assertEqual(end, TODAY)
        self.assertEqual((end - start).days + 1, 365)

    def test_leap_year_range(self):
        start, end = resolve_range(DataRequest(days=366), dt.date(2028, 12, 31))
        self.assertEqual(start, dt.date(2028, 1, 1))

    def test_explicit_dates_override_days(self):
        start, end = resolve_range(DataRequest(start=dt.date(2026, 1, 1), end=dt.date(2026, 3, 1), days=999), TODAY)
        self.assertEqual((start, end), (dt.date(2026, 1, 1), dt.date(2026, 3, 1)))

    def test_invalid_ranges(self):
        bad = [DataRequest(days=3), DataRequest(days=5000), DataRequest(start=TODAY, end=TODAY - dt.timedelta(days=30)),
               DataRequest(start=dt.date(2020, 1, 1), end=TODAY)]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(ConfigError):
                resolve_range(request, TODAY)


class LoadSeriesTests(unittest.TestCase):
    def test_demo_is_offline_deterministic_and_needs_no_token(self):
        a = load_series(DataRequest(source="demo"), today=TODAY)
        b = load_series(DataRequest(source="demo", days=365), today=TODAY + dt.timedelta(days=50))
        self.assertEqual(a, b)  # demo ignores "today": same data every time
        self.assertEqual((len(a), a.source), (365, "demo"))
        self.assertEqual(len(load_series(DataRequest(source="demo", days=30))), 30)

    def test_json_file(self):
        path = ROOT / "examples" / "sample-contributions.json"
        series = load_series(DataRequest(source="json", input_json=path))
        self.assertEqual((len(series), series.source), (365, "json"))
        self.assertEqual(series.counts, demo().counts)
        self.assertEqual(len(load_series(DataRequest(source="json", input_json=path, days=60))), 60)
        clipped = load_series(DataRequest(source="json", input_json=path, start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1)))
        self.assertEqual(len(clipped), 32)

    def test_json_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{nope")
            with self.assertRaises(DataError):
                load_series(DataRequest(source="json", input_json=bad))
            with self.assertRaises(DataError):
                load_series(DataRequest(source="json", input_json=Path(tmp) / "missing.json"))
            empty = Path(tmp) / "empty.json"
            empty.write_text("[]")
            with self.assertRaises(DataError):
                load_series(DataRequest(source="json", input_json=empty))
            short = Path(tmp) / "short.json"
            short.write_text(json.dumps([{"date": "2026-01-01", "count": 1}] * 1))
            with self.assertRaises(DataError):
                load_series(DataRequest(source="json", input_json=short))
        with self.assertRaises(ConfigError):
            load_series(DataRequest(source="json"))
        with self.assertRaises(ConfigError):
            load_series(DataRequest(source="json", input_json=ROOT / "examples" / "sample-contributions.json", days=3))

    def test_github_uses_the_client_with_the_resolved_range(self):
        client = FakeClient()
        request = DataRequest(source="github", username="Sumit6258", days=30, include_private=True)
        series = load_series(request, today=TODAY, client=client)
        username, start, end, private = client.calls[0]
        self.assertEqual((username, end, private), ("Sumit6258", TODAY, True))
        self.assertEqual((end - start).days + 1, 30)
        self.assertEqual(series.username, "Sumit6258")

    def test_github_validation(self):
        with self.assertRaises(ConfigError):
            load_series(DataRequest(source="github"), client=FakeClient())
        with self.assertRaises(ConfigError):
            load_series(DataRequest(source="github", username="bad name"), client=FakeClient())
        with self.assertRaises(MissingTokenError):  # no client injected and no token
            load_series(DataRequest(source="github", username="octocat"), today=TODAY)
        with self.assertRaises(ConfigError):
            load_series(DataRequest(source="carrier-pigeon"))

    def test_limits_are_the_documented_ones(self):
        self.assertEqual((d.MIN_DAYS, d.MAX_DAYS), (7, 1100))


if __name__ == "__main__":
    unittest.main()
