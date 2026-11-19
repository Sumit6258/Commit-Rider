import datetime as dt
import json
import unittest

from commit_rider.data.demo import generate_demo_series
from commit_rider.data.models import ContributionDay
from commit_rider.data.normalization import normalize_series
from commit_rider.data.stats import compute_stats
from commit_rider.data.validation import (
    days_from_records,
    parse_contribution_json,
    parse_count,
    parse_date,
    validate_username,
)
from commit_rider.errors import ConfigError, DataError
from tests.support import series_from_counts


class UsernameTests(unittest.TestCase):
    def test_valid(self):
        for name in ("Sumit6258", "a", "octo-cat", "A1", "x" * 39, "user_abc"):
            self.assertEqual(validate_username(name), name)

    def test_invalid(self):
        for name in ("", "-bad", "bad-", "has space", "x" * 40, "semi;colon", "../etc", "a/b", None):
            with self.subTest(name=name), self.assertRaises(ConfigError):
                validate_username(name)  # type: ignore[arg-type]


class DateAndCountTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date("2026-11-15"), dt.date(2026, 11, 15))
        self.assertEqual(parse_date("2026-11-15T23:59:59Z"), dt.date(2026, 11, 15))

    def test_leap_years(self):
        self.assertEqual(parse_date("2028-02-29"), dt.date(2028, 2, 29))
        for bad in ("2026-02-29", "2100-02-29"):
            with self.subTest(bad=bad), self.assertRaises(DataError):
                parse_date(bad)

    def test_invalid_dates(self):
        for bad in ("2026-13-01", "not a date", "", None, 20260101, "2026-1-1x"):
            with self.subTest(bad=bad), self.assertRaises(DataError):
                parse_date(bad)

    def test_counts(self):
        self.assertEqual(parse_count(0), 0)
        self.assertEqual(parse_count(7.0), 7)
        for bad in (-1, 1.5, float("nan"), float("inf"), True, "3", None):
            with self.subTest(bad=bad), self.assertRaises(DataError):
                parse_count(bad)


class JsonParsingTests(unittest.TestCase):
    records = [{"date": "2026-01-01", "count": 3}, {"date": "2026-01-02", "count": 0}]

    def test_list_format(self):
        days = parse_contribution_json(json.dumps(self.records))
        self.assertEqual([d.count for d in days], [3, 0])

    def test_wrapped_formats(self):
        for key in ("days", "contributions"):
            days = parse_contribution_json(json.dumps({key: self.records}))
            self.assertEqual(len(days), 2)

    def test_raw_github_calendar_and_full_response(self):
        calendar = {"weeks": [{"contributionDays": [{"date": "2026-01-01", "contributionCount": 4}]}]}
        self.assertEqual(parse_contribution_json(json.dumps(calendar))[0].count, 4)
        full = {"data": {"user": {"contributionsCollection": {"contributionCalendar": calendar}}}}
        self.assertEqual(parse_contribution_json(json.dumps(full))[0].count, 4)

    def test_errors(self):
        cases = ["{not json", "42", '"text"', "{}", '[{"date": "2026-01-01"}]', '[{"count": 1}]',
                 '[{"date": "2026-01-01", "count": -2}]', '[1, 2]', '{"weeks": 5}']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(DataError):
                parse_contribution_json(text)

    def test_days_from_records_rejects_non_objects(self):
        with self.assertRaises(DataError):
            days_from_records([["2026-01-01", 1]])  # type: ignore[list-item]


class NormalizationTests(unittest.TestCase):
    def day(self, iso, n):
        return ContributionDay(dt.date.fromisoformat(iso), n)

    def test_sorts_and_fills_gaps(self):
        days = [self.day("2026-01-10", 2), self.day("2026-01-01", 5), self.day("2026-01-05", 1)]
        series = normalize_series(days)
        self.assertEqual(len(series), 10)
        self.assertEqual(series.days[0].date, dt.date(2026, 1, 1))
        self.assertEqual(series.filled_days, 7)
        self.assertEqual(series.total, 8)
        self.assertEqual(series.counts[1], 0)

    def test_clipping_and_padding_to_range(self):
        days = [self.day("2026-01-01", 5), self.day("2026-01-20", 1)]
        series = normalize_series(days, start=dt.date(2026, 1, 10), end=dt.date(2026, 1, 25))
        self.assertEqual((series.start, series.end), (dt.date(2026, 1, 10), dt.date(2026, 1, 25)))
        self.assertEqual(series.total, 1)

    def test_leap_day_is_a_normal_day(self):
        days = [self.day("2028-02-27", 1), self.day("2028-03-05", 1)]
        series = normalize_series(days)
        self.assertEqual(len(series), 8)
        self.assertIn(dt.date(2028, 2, 29), [d.date for d in series.days])

    def test_errors(self):
        with self.assertRaises(DataError):
            normalize_series([])
        with self.assertRaises(DataError):
            normalize_series([self.day("2026-01-01", 1), self.day("2026-01-01", 2)] + [self.day("2026-01-09", 0)])
        with self.assertRaises(DataError):  # too short
            normalize_series([self.day("2026-01-01", 1), self.day("2026-01-03", 1)])
        with self.assertRaises(DataError):  # too long
            normalize_series([self.day("2020-01-01", 1), self.day("2026-01-01", 1)])
        with self.assertRaises(DataError):
            normalize_series([self.day("2026-01-01", 1)] * 1 + [self.day("2026-01-09", -1)])
        with self.assertRaises(DataError):
            normalize_series([self.day("2026-01-01", 1)], start=dt.date(2026, 2, 1), end=dt.date(2026, 1, 1))


class StatsTests(unittest.TestCase):
    def test_basic(self):
        stats = compute_stats(series_from_counts([0, 2, 5, 0, 3, 4, 1, 0, 0, 2]))
        self.assertEqual(stats.total, 17)
        self.assertEqual(stats.max_count, 5)
        self.assertEqual(stats.max_date, dt.date(2026, 1, 3))
        self.assertEqual(stats.active_days, 6)
        self.assertEqual(stats.longest_streak, 3)
        self.assertAlmostEqual(stats.average, 1.7)

    def test_current_streak_semantics(self):
        self.assertEqual(compute_stats(series_from_counts([0, 0, 0, 0, 0, 0, 1, 2, 3])).current_streak, 3)
        # a zero on the last day does not break the streak (the day may not be over yet)
        self.assertEqual(compute_stats(series_from_counts([0, 0, 0, 0, 0, 1, 2, 3, 0])).current_streak, 3)
        self.assertEqual(compute_stats(series_from_counts([1, 1, 0, 0, 0, 0, 0, 0, 0])).current_streak, 0)

    def test_all_zero(self):
        stats = compute_stats(series_from_counts([0] * 9))
        self.assertEqual((stats.total, stats.max_count, stats.current_streak, stats.longest_streak), (0, 0, 0, 0))


class DemoDataTests(unittest.TestCase):
    def test_deterministic_and_contiguous(self):
        a, b = generate_demo_series(), generate_demo_series()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 365)
        self.assertEqual((a.days[-1].date - a.days[0].date).days, 364)
        self.assertEqual(a.source, "demo")

    def test_has_texture(self):
        counts = generate_demo_series().counts
        self.assertGreater(max(counts), 25)
        self.assertGreater(counts.count(0), 10)

    def test_other_seed_differs(self):
        self.assertNotEqual(generate_demo_series(seed=1).counts, generate_demo_series(seed=2).counts)


if __name__ == "__main__":
    unittest.main()
