import math
import unittest

from commit_rider.errors import ConfigError, DataError
from commit_rider.terrain.generator import TerrainParams, generate_terrain
from commit_rider.terrain.interpolation import (
    gaussian_kernel,
    limit_rate,
    pchip_slopes_periodic,
    sample_periodic_pchip,
    smooth_circular,
    smoothstep,
)
from commit_rider.terrain.scaling import activity_levels, percentile, reference_count, scale_counts
from tests.support import demo


class ScalingTests(unittest.TestCase):
    def test_empty_and_all_zero(self):
        self.assertEqual(scale_counts([]), [])
        self.assertEqual(scale_counts([0, 0, 0]), [0.0, 0.0, 0.0])

    def test_identical_counts_give_a_flat_mid_level(self):
        self.assertEqual(scale_counts([5] * 6), [0.5] * 6)

    def test_single_active_day_is_the_peak(self):
        levels = scale_counts([0, 0, 9, 0])
        self.assertEqual(levels, [0.0, 0.0, 1.0, 0.0])

    def test_monotonic_in_count(self):
        for method in ("log", "sqrt", "linear", "rank"):
            counts = [0, 1, 2, 3, 5, 8, 13, 21, 34]
            levels = scale_counts(counts, method)
            self.assertEqual(levels, sorted(levels), method)
            self.assertEqual(levels[0], 0.0)
            self.assertTrue(all(b > a for a, b in zip(levels, levels[1:])), method)

    def test_outlier_does_not_flatten_everything_else(self):
        base = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12] * 3
        with_spike = base + [5000]
        a = scale_counts(base)
        b = scale_counts(with_spike)[:-1]
        # ordinary days keep (almost) the same height with or without a 5000-commit day
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, delta=0.2)
        self.assertGreater(scale_counts(with_spike)[-1], 1.0)  # ...and the spike is still a peak
        self.assertLessEqual(scale_counts(with_spike)[-1], 1.35 + 1e-9)  # ...but bounded

    def test_percentile_helpers(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0), 1)
        self.assertAlmostEqual(percentile([1, 2], 0.25), 1.25)
        self.assertEqual(reference_count([0, 0, 0]), 0.0)
        with self.assertRaises(ValueError):
            percentile([], 0.5)
        with self.assertRaises(ValueError):
            percentile([1], 1.5)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            scale_counts([1, 2], "magic")
        with self.assertRaises(ValueError):
            scale_counts([1, -2])
        with self.assertRaises(ValueError):
            scale_counts([1, 2], soft_cap=1.0)

    def test_activity_levels(self):
        levels = activity_levels([0, 1, 2, 3, 4, 5, 6, 7, 8, 100])
        self.assertEqual(levels[0], 0)
        self.assertEqual(levels[-1], 4)
        self.assertEqual(list(levels), sorted(levels))
        self.assertEqual(activity_levels([0, 0]), (0, 0))


class InterpolationTests(unittest.TestCase):
    def test_pchip_passes_through_control_points(self):
        y = [0, 3, 1, 7, 2, 2, 9, 0]
        out = sample_periodic_pchip(y, 8)
        self.assertEqual(len(out), len(y) * 8)
        for i, v in enumerate(y):
            self.assertAlmostEqual(out[i * 8], v)

    def test_pchip_never_overshoots(self):
        y = [0, 0, 0, 10, 0, 0, 0, 0]
        out = sample_periodic_pchip(y, 10)
        self.assertGreaterEqual(min(out), -1e-9)
        self.assertLessEqual(max(out), 10 + 1e-9)

    def test_pchip_is_periodic_and_smooth_at_the_seam(self):
        y = [2, 5, 3, 8, 1, 4]
        out = sample_periodic_pchip(y, 50)
        self.assertLess(abs(out[0] - y[0]), 1e-9)
        step_seam = out[0] - out[-1]
        step_typical = max(abs(out[i + 1] - out[i]) for i in range(len(out) - 1))
        self.assertLessEqual(abs(step_seam), step_typical + 1e-9)

    def test_pchip_input_validation(self):
        with self.assertRaises(ValueError):
            sample_periodic_pchip([1.0], 4)
        with self.assertRaises(ValueError):
            sample_periodic_pchip([1.0, 2.0], 0)
        self.assertEqual(pchip_slopes_periodic([1, 1, 1]), [0.0, 0.0, 0.0])

    def test_smoothing_preserves_constants_and_mean(self):
        self.assertEqual(smooth_circular([4.0] * 20, 2.0), [4.0] * 20)
        data = [0, 0, 9, 0, 0, 3, 0, 0, 0, 1]
        out = smooth_circular(data, 1.5)
        self.assertAlmostEqual(sum(out), sum(data), places=6)
        self.assertEqual(smooth_circular(data, 0.0), data)
        self.assertAlmostEqual(sum(gaussian_kernel(2.0)), 1.0)

    def test_smoothstep_and_limit_rate(self):
        self.assertEqual((smoothstep(-1), smoothstep(0.5), smoothstep(2)), (0.0, 0.5, 1.0))
        stepped = [0.0] * 30 + [10.0] * 30
        limited = limit_rate(stepped, 0.5)
        worst = max(abs(limited[(i + 1) % 60] - limited[i]) for i in range(60))
        self.assertLessEqual(worst, 0.5 + 1e-9)
        gentle = [math.sin(i / 9) for i in range(60)]
        self.assertEqual(limit_rate(gentle, 5.0), [(a + b) / 2 for a, b in zip(gentle, gentle)])


class TerrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = demo().counts
        cls.terrain = generate_terrain(cls.counts)

    def test_deterministic(self):
        again = generate_terrain(self.counts)
        self.assertEqual(self.terrain.heights, again.heights)
        self.assertNotEqual(self.terrain.heights, generate_terrain(self.counts, TerrainParams(seed=3)).heights)

    def test_geometry_basics(self):
        t = self.terrain
        self.assertEqual(t.num_days, 365)
        self.assertAlmostEqual(t.period, (365 + 16) * 14.0)
        self.assertGreater(t.min_height, 0)
        self.assertAlmostEqual(t.height(0.0), t.height(t.period))
        self.assertAlmostEqual(t.height(5.5), t.height(5.5 + 3 * t.period))
        self.assertIsNone(t.day_index_at(t.data_length + 1))
        self.assertEqual(t.day_index_at(0.1), 0)
        self.assertEqual(t.day_index_at(14.5), 1)

    def test_loop_seam_is_smooth(self):
        t = self.terrain
        self.assertLess(abs(t.heights[0] - t.heights[-1]), 1.5 * t.dx)  # no step
        seam = abs(t.slopes[0] - t.slopes[-1])  # no kink: no sharper than anywhere else
        elsewhere = max(abs(t.slopes[i + 1] - t.slopes[i]) for i in range(t.n - 1))
        self.assertLessEqual(seam, elsewhere)
        self.assertLess(seam, 0.1)
        self.assertAlmostEqual(t.slope(0.0), t.slope(t.period), places=6)

    def test_slope_limit_is_exact(self):
        t = self.terrain
        self.assertLessEqual(max(abs(s) for s in t.slopes), 1.0 + 1e-6)
        steepest = max(abs(t.heights[(i + 1) % t.n] - t.heights[i]) / t.dx for i in range(t.n))
        self.assertLessEqual(steepest, 1.0 + 1e-6)

    def test_busy_stretches_are_higher_than_quiet_ones(self):
        counts = [0] * 40 + [12] * 40 + [0] * 40
        t = generate_terrain(counts)
        quiet = t.height(20 * 14.0)
        busy = t.height(60 * 14.0)
        self.assertGreater(busy, quiet + 40)

    def test_all_zero_is_a_gentle_valley(self):
        t = generate_terrain([0] * 30)
        self.assertLess(t.max_height - t.min_height, 12)
        self.assertGreater(t.min_height, 0)

    def test_single_active_day_makes_one_hill(self):
        counts = [0] * 60
        counts[30] = 7
        t = generate_terrain(counts)
        peak_x = max(range(t.n), key=lambda i: t.heights[i]) * t.dx
        self.assertAlmostEqual(peak_x, 30.5 * 14.0, delta=14.0)
        self.assertGreater(t.max_height - t.min_height, 60)  # auto-contrast keeps it visible

    def test_auto_contrast_only_scales_sparse_profiles(self):
        sparse = [0] * 80
        sparse[40] = 5
        quiet = generate_terrain(sparse)
        self.assertGreater(quiet.max_height - quiet.min_height, 60)
        busy = generate_terrain(demo().counts)
        same = generate_terrain(demo().counts, TerrainParams(sigma_days=1.2))
        self.assertEqual(busy.heights, same.heights)  # dense data: gain is exactly 1
        # relative heights are preserved: the higher day stays the higher hill
        two = [0] * 90
        two[20], two[60] = 3, 12
        t = generate_terrain(two)
        self.assertGreater(t.height(60.5 * 14.0), t.height(20.5 * 14.0) + 10)

    def test_identical_counts_are_flat(self):
        t = generate_terrain([6] * 40, TerrainParams(bridge_days=8))
        main = t.heights[: int(30 * t.day_width / t.dx)]
        self.assertLess(max(main) - min(main), 25)

    def test_extreme_spike_keeps_small_hills_visible(self):
        base = [0, 0, 3, 0, 5, 1, 0, 4, 0, 2] * 6
        calm = generate_terrain(base)
        spiky = generate_terrain(base[:30] + [3000] + base[31:])
        hill = int(44 * calm.day_width / calm.dx)  # a small day-4 style hill far from the spike
        rel_calm = calm.heights[hill] - calm.min_height
        rel_spiky = spiky.heights[hill] - spiky.min_height
        self.assertGreater(rel_spiky, 0.6 * rel_calm)

    def test_consecutive_zero_days_stay_smooth(self):
        counts = [8] * 10 + [0] * 60 + [8] * 10
        t = generate_terrain(counts)
        gap = t.heights[int(20 * t.day_width / t.dx) : int(60 * t.day_width / t.dx)]
        self.assertLess(max(gap) - min(gap), 15)

    def test_modes_change_the_shape(self):
        mountain = generate_terrain(self.counts, TerrainParams(amplitude=150, gamma=1.35))
        rolling = generate_terrain(self.counts, TerrainParams(amplitude=78, sigma_days=2.2, gamma=0.9))
        self.assertGreater(mountain.max_height - mountain.min_height, rolling.max_height - rolling.min_height)
        arcade = generate_terrain(self.counts, TerrainParams(quantize=True))
        ramps = generate_terrain(self.counts, TerrainParams(skew_days=2.2))
        self.assertNotEqual(arcade.heights, self.terrain.heights)
        self.assertNotEqual(ramps.heights, self.terrain.heights)

    def test_invalid_inputs(self):
        with self.assertRaises(DataError):
            generate_terrain([])
        with self.assertRaises(DataError):
            generate_terrain([1, -1, 2])
        with self.assertRaises(DataError):
            generate_terrain([1, 2.5, 3])  # type: ignore[list-item]
        with self.assertRaises(ConfigError):
            TerrainParams(day_width=1)
        with self.assertRaises(ConfigError):
            TerrainParams(bridge_days=1)
        with self.assertRaises(ConfigError):
            TerrainParams(amplitude=0)

    def test_extreme_data_respects_the_slope_limit(self):
        counts = [0] * 50 + [900] + [0] * 50
        t = generate_terrain(counts, TerrainParams(amplitude=224, sigma_days=0.7))
        self.assertLessEqual(max(abs(s) for s in t.slopes), 1.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
