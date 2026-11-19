import json
import tempfile
import unittest
from pathlib import Path

from commit_rider.config import defaults as d
from commit_rider.config.settings import Settings, normalize_color, option_schema
from commit_rider.errors import ConfigError
from commit_rider.rendering.colors import darken, lighten, luminance, mix, rgb, to_hex
from commit_rider.rendering.themes import (
    THEMES,
    get_theme,
    load_theme_file,
    register_theme,
    theme_from_mapping,
    theme_names,
)


class SettingsTests(unittest.TestCase):
    def test_defaults_match_the_specification(self):
        s = Settings()
        self.assertEqual((s.width, s.height, s.fps, s.duration), (1200, 360, 18, 8.0))
        self.assertEqual(s.frames, 144)
        self.assertEqual((s.theme, s.bike, s.particles, s.show_stats), ("midnight", "bmx", True, False))

    def test_invalid_values_are_all_reported_at_once(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings(width=10, fps=99, theme="nope", smoothing=3, bike_color="red")
        message = str(ctx.exception)
        for fragment in ("width", "fps", "theme", "smoothing", "bike_color"):
            self.assertIn(fragment, message)

    def test_resource_limits(self):
        with self.assertRaises(ConfigError):
            Settings(duration=30, fps=30)  # 900 frames
        with self.assertRaises(ConfigError):
            Settings(width=2400, height=900, fps=30, duration=15)  # too much pixel work
        Settings(width=2400, height=900, fps=10, duration=5)  # allowed

    def test_derived_values(self):
        s = Settings(height=180, width=600)
        self.assertAlmostEqual(s.unit, 0.5)
        self.assertAlmostEqual(s.view_width, 1200.0)
        self.assertAlmostEqual(Settings(ride_mode="speed", speed=1.2).effective_speed, 1.3 * 1.2)
        self.assertEqual(Settings(ride_mode="stunt").effective_stunts, 0.95)
        self.assertEqual(Settings(ride_mode="stunt", stunt_intensity=0.2).effective_stunts, 0.2)

    def test_from_mapping_coerces_strings_like_action_inputs(self):
        s = Settings.from_mapping(
            {"theme": "NEON", "width": "1000", "duration": "6.5", "particles": "false", "ride-mode": "stunt",
             "seed": "4", "stunt-intensity": "", "bike-color": "#F0C"}
        )
        self.assertEqual((s.theme, s.width, s.duration, s.particles, s.ride_mode, s.seed), ("neon", 1000, 6.5, False, "stunt", 4))
        self.assertIsNone(s.stunt_intensity)
        self.assertEqual(s.bike_color, "#ff00cc")

    def test_from_mapping_errors(self):
        for bad in ({"width": "wide"}, {"fps": 1.5}, {"particles": "maybe"}, {"duration": "x"}, {"nonsense": 1}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                Settings.from_mapping(bad)

    def test_round_trip_and_changes(self):
        s = Settings(theme="snow", seed=9)
        self.assertEqual(Settings.from_mapping(s.to_dict()), s)
        self.assertEqual(s.with_changes(theme="forest").theme, "forest")
        with self.assertRaises(ConfigError):
            s.with_changes(width=1)

    def test_schema_covers_every_setting(self):
        schema = option_schema()
        self.assertEqual(set(schema), set(Settings().to_dict()))
        self.assertEqual(schema["theme"]["enum"], list(theme_names()))
        self.assertEqual(schema["fps"]["default"], 18)
        json.dumps(schema)  # serialisable for a future web configurator

    def test_colors(self):
        self.assertEqual(normalize_color("#ABC"), "#aabbcc")
        self.assertEqual(normalize_color("1f6feb"), "#1f6feb")
        for bad in ("#12", "blue", "#gggggg", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_color(bad)

    def test_presets_are_consistent(self):
        self.assertEqual(set(d.RIDE_MODES), {"normal", "speed", "stunt", "relaxed"})
        self.assertEqual(set(d.TERRAIN_MODES), {"natural", "rolling", "ramps", "mountain", "arcade"})
        self.assertEqual(d.QUALITY_PRESETS["standard"].supersample, 2)


class ColorTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(rgb("#102030"), (16, 32, 48))
        self.assertEqual(rgb("fff"), (255, 255, 255))
        self.assertEqual(to_hex((1, 2, 3)), "#010203")
        self.assertEqual(mix("#000000", "#ffffff", 0.5), (128, 128, 128))
        self.assertEqual(darken("#ffffff", 1.0), (0, 0, 0))
        self.assertEqual(lighten("#000000", 1.0), (255, 255, 255))
        self.assertLess(luminance("#101010"), luminance("#f0f0f0"))
        with self.assertRaises(ValueError):
            rgb("#12345")


class ThemeTests(unittest.TestCase):
    def test_all_seven_requested_themes_exist(self):
        self.assertEqual(
            set(theme_names()), {"midnight", "forest", "sunset", "neon", "snow", "minimal", "monochrome"}
        )

    def test_every_colour_in_every_theme_is_valid(self):
        for name, theme in THEMES.items():
            for field, value in vars(theme).items():
                with self.subTest(theme=name, field=field):
                    if isinstance(value, str) and value.startswith("#"):
                        rgb(value)
            for _, color in theme.sky:
                rgb(color)
            self.assertEqual(len(theme.trail), 5)
            for layer in theme.layers:
                rgb(layer.color)
                self.assertGreater(layer.parallax, 0)

    def test_overrides(self):
        theme = get_theme("forest").with_overrides(bike_color="#ff0000", rider_color="#00ff00",
                                                   terrain_color="#303030", background_color="#101820")
        self.assertEqual((theme.frame, theme.jersey, theme.terrain_top), ("#ff0000", "#00ff00", "#303030"))
        self.assertEqual(theme.sky[-1][1], "#101820")
        self.assertEqual(get_theme("forest").with_overrides(), get_theme("forest"))

    def test_custom_theme_from_mapping_and_file(self):
        theme = theme_from_mapping({"name": "ocean", "base": "snow", "frame": "#0077ff", "sky": [[0, "#001"], [1, "#02a"]]})
        self.assertEqual((theme.name, theme.frame), ("ocean", "#0077ff"))
        self.assertEqual(theme.layers, get_theme("snow").layers)  # inherited from the base
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_text(json.dumps({"name": "filetheme", "jersey": "#123456"}))
            self.addCleanup(THEMES.pop, "filetheme", None)
            loaded = load_theme_file(path)
            self.assertEqual(loaded.jersey, "#123456")
            self.assertEqual(Settings(theme="filetheme").theme, "filetheme")

    def test_custom_theme_errors(self):
        bad_cases = (
            {}, {"name": "x", "bogus": 1}, {"name": "x", "frame": "notacolour"}, {"name": "x", "base": "missing"},
            {"name": "x", "sky": [[0, "#000"]]}, {"name": "x", "trail": ["#000"] * 4},
            {"name": "x", "stars": "many"}, {"name": "x", "celestial": "comet"},
            {"name": "x", "layers": [{"kind": "cliffs", "color": "#000", "parallax": 0.3, "base": 0.6, "amplitude": 10}]},
            {"name": "x", "jersey": 12345},
        )
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                theme_from_mapping(bad)
        with tempfile.TemporaryDirectory() as tmp:
            for content in ("{bad json", "[1]"):
                path = Path(tmp) / "bad.json"
                path.write_text(content)
                with self.assertRaises(ConfigError):
                    load_theme_file(path)
            with self.assertRaises(ConfigError):
                load_theme_file(Path(tmp) / "missing.json")

    def test_register_theme(self):
        theme = theme_from_mapping({"name": "zz-test"})
        register_theme(theme)
        self.addCleanup(THEMES.pop, "zz-test", None)
        self.assertIn("zz-test", theme_names())
        with self.assertRaises(ConfigError):
            get_theme("not-registered")


if __name__ == "__main__":
    unittest.main()
