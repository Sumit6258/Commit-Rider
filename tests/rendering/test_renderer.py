import io
import math
import unittest
from contextlib import contextmanager

from PIL import Image, ImageChops, ImageStat

from commit_rider.rendering.background import ridge_profile
from commit_rider.rendering.colors import rgb
from commit_rider.rendering.exporter import encode_gif
from commit_rider.rendering.renderer import Renderer
from commit_rider.rendering.themes import theme_names
from tests.support import demo, small_settings


def mean_abs_diff(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def count_near(image, color, tolerance=36, box=None):
    target = rgb(color)
    region = image.crop(box) if box else image
    data = region.tobytes()
    total = 0
    for i in range(0, len(data), 3):
        if abs(data[i] - target[0]) + abs(data[i + 1] - target[1]) + abs(data[i + 2] - target[2]) <= tolerance:
            total += 1
    return total


def changed_pixels(a, b, threshold=12):
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > threshold else 0)
    return diff.histogram()[255]


@contextmanager
def sprites_hidden(renderer):
    original = renderer.sprites.draw
    renderer.sprites.draw = lambda *args, **kwargs: None
    try:
        yield
    finally:
        renderer.sprites.draw = original


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = small_settings()
        cls.renderer = Renderer(demo(), cls.settings)
        cls.frames = [cls.renderer.render_frame(k) for k in range(cls.settings.frames)]

    def test_dimensions_mode_and_count(self):
        self.assertEqual(len(self.frames), 30)
        for frame in self.frames:
            self.assertEqual((frame.size, frame.mode), ((480, 144), "RGB"))

    def test_rendering_is_deterministic(self):
        again = self.renderer.render_frame(7)
        self.assertEqual(again.tobytes(), self.frames[7].tobytes())
        other = Renderer(demo(), self.settings).render_frame(7)
        self.assertEqual(other.tobytes(), self.frames[7].tobytes())

    def test_no_blank_frames(self):
        for k, frame in enumerate(self.frames):
            self.assertGreater(len(frame.getcolors(maxcolors=1_000_000)), 100, f"frame {k}")
            self.assertTrue(all(lo != hi for lo, hi in frame.getextrema()), f"frame {k}")

    def test_first_and_final_frames_are_continuous(self):
        r, n = self.renderer, self.settings.frames
        self.assertEqual(r.render_frame(n).tobytes(), self.frames[0].tobytes())  # frame after the last == first
        changes = [mean_abs_diff(self.frames[k], self.frames[k + 1]) for k in range(n - 1)]
        seam = mean_abs_diff(self.frames[-1], self.frames[0])
        self.assertLessEqual(seam, 1.25 * max(changes))
        self.assertGreater(seam, 0)  # it is a real animation step, not a frozen frame

    def test_rider_and_bicycle_are_visible_in_every_frame(self):
        r = self.renderer
        for k in range(0, self.settings.frames, 3):
            frame = self.frames[k]
            with sprites_hidden(r):
                bare = r.render_frame(k)
            self.assertGreater(changed_pixels(frame, bare), 800, f"sprites barely visible in frame {k}")
            box = r.sprites.bounds(r.timeline.frame(k))
            self.assertTrue(0 < (box[0] + box[2]) / 2 < self.settings.width)
            theme = r.theme
            self.assertGreater(count_near(frame, theme.frame, 40, box), 15, f"bike frame colour missing in {k}")
            self.assertGreater(count_near(frame, theme.jersey, 40, box), 15, f"jersey colour missing in {k}")

    def test_both_wheels_are_complete_circles_in_every_frame(self):
        r, s = self.renderer, self.settings
        tire = rgb(r.theme.tire)
        for k in range(s.frames):
            fr = r.timeline.frame(k)
            for offset in (0.0, r.timeline.bike.wheelbase):
                cx = fr.rear[0] + offset * math.cos(fr.pitch)
                cy = fr.rear[1] + offset * math.sin(fr.pitch)
                hits = 0
                samples = 36
                for i in range(samples):
                    a = math.tau * i / samples
                    wx, wy = cx + 24.5 * math.cos(a), cy + 24.5 * math.sin(a)
                    px = (wx - fr.cam_x) * s.unit
                    py = r.sprites.anchor_px - (wy - fr.cam_y) * s.unit
                    if 0 <= px < s.width and 0 <= py < s.height:
                        c = self.frames[k].getpixel((int(px), int(py)))
                        hits += sum(abs(c[j] - tire[j]) for j in range(3)) < 90
                self.assertGreaterEqual(hits, 0.55 * samples, f"a wheel is missing or cut in frame {k}")

    def test_sprites_are_never_clipped_by_the_frame(self):
        r, s = self.renderer, self.settings
        for k in range(s.frames):
            x0, y0, x1, y1 = r.sprites.bounds(r.timeline.frame(k))
            self.assertGreaterEqual(y0, -2, f"head leaves the top in frame {k}")
            self.assertLessEqual(y1, s.height + 2, f"wheels leave the bottom in frame {k}")
            self.assertGreaterEqual(x0, 0)
            self.assertLessEqual(x1, s.width)

    def test_terrain_is_drawn_where_the_geometry_says(self):
        # Larger canvas: at 144 px the trail band is under 3 px thick and blends out of tolerance.
        s = small_settings(width=960, height=288, fps=6, duration=2.0)
        r = Renderer(demo(), s)
        palette = [rgb(c) for c in (r.theme.terrain_edge, r.theme.decor_color, *r.theme.trail[1:])]
        for k in (2, 5, 9):
            fr = r.timeline.frame(k)
            image = r.render_frame(k)
            for column in (10, s.width - 10):
                world_x = fr.cam_x + column / s.unit
                expected = r.sprites.anchor_px - (r.terrain.height(world_x) - fr.cam_y) * s.unit
                found = None
                for y in range(s.height):
                    px = image.getpixel((column, y))
                    if any(sum(abs(px[i] - c[i]) for i in range(3)) < 70 for c in palette):
                        found = y
                        break
                self.assertIsNotNone(found, f"no terrain surface in column {column} of frame {k}")
                self.assertLess(abs(found - expected), 8, f"frame {k} column {column}: {found} vs {expected:.1f}")

    def test_no_unexpected_transparency_after_gif_roundtrip(self):
        data, _ = encode_gif(self.frames, self.settings.fps, 255, 0)
        gif = Image.open(io.BytesIO(data))
        for k in range(gif.n_frames):
            gif.seek(k)
            low, _ = gif.convert("RGBA").getchannel("A").getextrema()
            self.assertEqual(low, 255, f"transparent pixels in frame {k}")

    def test_global_palette_means_the_static_sky_never_flickers(self):
        data, _ = encode_gif(self.frames, self.settings.fps, 255, 0)
        gif = Image.open(io.BytesIO(data))
        patches = []
        for k in range(gif.n_frames):
            gif.seek(k)
            patches.append(gif.convert("RGB").crop((0, 0, 40, 6)))
        for a, b in zip(patches, patches[1:]):
            self.assertLess(mean_abs_diff(a, b), 3.0)

    def test_big_air_stays_in_frame_in_stunt_mode(self):
        r = Renderer(demo(), small_settings(ride_mode="stunt", fps=24, duration=8.0))
        self.assertGreaterEqual(sum(f.flips for f in r.timeline.plan.flights), 1)
        for k in range(r.settings.frames):
            x0, y0, x1, y1 = r.sprites.bounds(r.timeline.frame(k))
            self.assertGreaterEqual(y0, -2, f"rider leaves the top during a stunt, frame {k}")
            self.assertLessEqual(y1, r.settings.height + 2, f"frame {k}")

    def test_terrain_layer_covers_exactly_one_lap(self):
        r = self.renderer
        self.assertAlmostEqual(r.strip.image.width / r.strip.kx, r.terrain.period, delta=1)

    def test_background_layers_tile_exactly_one_scroll_per_lap(self):
        r = self.renderer
        for spec, tile in r.background.layers:
            self.assertEqual(tile.width, max(8, round(spec.parallax * r.terrain.period * r.ppu)))


class BackgroundMathTests(unittest.TestCase):
    def test_ridge_profiles_are_periodic_and_bounded(self):
        for kind in ("mountains", "hills"):
            values = ridge_profile(900, 5, kind)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
            steps = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
            self.assertLessEqual(abs(values[0] - values[-1]), max(steps) * 1.5 + 1e-9)  # tiles join seamlessly
            self.assertEqual(values, ridge_profile(900, 5, kind))  # deterministic
            self.assertNotEqual(values, ridge_profile(900, 6, kind))


class ThemeAndOptionTests(unittest.TestCase):
    def test_every_theme_renders_with_a_visible_rider(self):
        for name in theme_names():
            with self.subTest(theme=name):
                s = small_settings(theme=name, width=320, height=96, fps=6, duration=2.0)
                r = Renderer(demo(), s)
                frame = r.render_frame(4)
                with sprites_hidden(r):
                    bare = r.render_frame(4)
                self.assertGreater(changed_pixels(frame, bare, 14), 150, "rider invisible against the background")

    def test_sprite_colours_do_not_blend_into_what_is_behind_them(self):
        """Poor-contrast check: render the scene *without* the sprites and measure how much of
        the area behind the rider already has the jersey or frame colour."""
        for name in theme_names():
            s = small_settings(theme=name, width=480, height=144, fps=6, duration=2.0)
            r = Renderer(demo(), s)
            for k in (2, 5, 8):
                with sprites_hidden(r):
                    bare = r.render_frame(k)
                box = r.sprites.bounds(r.timeline.frame(k))
                box = (max(0, box[0]), max(0, box[1]), min(s.width, box[2]), min(s.height, box[3]))
                area = (box[2] - box[0]) * (box[3] - box[1])
                for label, colour in (("jersey", r.theme.jersey), ("frame", r.theme.frame)):
                    share = count_near(bare, colour, 45, box) / area
                    self.assertLess(share, 0.12, f"{name} frame {k}: {label} colour is {share:.0%} of the backdrop")

    def test_quality_presets_and_modes_render(self):
        for quality in ("draft", "standard", "high"):
            r = Renderer(demo(), small_settings(quality=quality, width=320, height=96, fps=6, duration=2.0))
            self.assertEqual(r.render_frame(1).size, (320, 96))
        tiny = {"width": 320, "height": 96, "fps": 6, "duration": 2.0}
        for terrain_mode in ("natural", "rolling", "ramps", "mountain", "arcade"):
            r = Renderer(demo(), small_settings(terrain_mode=terrain_mode, **tiny))
            self.assertEqual(r.render_frame(2).size, (320, 96))
        for ride_mode in ("speed", "stunt", "relaxed"):
            r = Renderer(demo(), small_settings(ride_mode=ride_mode, **tiny))
            self.assertEqual(r.render_frame(2).size, (320, 96))

    def test_colour_overrides_reach_the_pixels(self):
        s = small_settings(bike_color="#ff00ff", rider_color="#00ff66", width=320, height=96, fps=6, duration=2.0)
        r = Renderer(demo(), s)
        frame = r.render_frame(3)
        box = r.sprites.bounds(r.timeline.frame(3))
        self.assertGreater(count_near(frame, "#ff00ff", 60, box), 5)
        self.assertGreater(count_near(frame, "#00ff66", 60, box), 5)

    def test_particles_can_be_disabled(self):
        on = Renderer(demo(), small_settings(particles=True, width=320, height=96, fps=6, duration=2.0))
        off = Renderer(demo(), small_settings(particles=False, width=320, height=96, fps=6, duration=2.0))
        self.assertTrue(on.timeline.puffs)
        self.assertEqual(off.timeline.puffs, [])

    def test_stats_overlay_and_date_ticker(self):
        base = small_settings(width=640, height=192, fps=6, duration=2.0)
        plain = Renderer(demo(), base)
        with_stats = Renderer(demo(), base.with_changes(show_stats=True))
        self.assertIsNone(plain.overlay)
        a, b = plain.render_frame(2), with_stats.render_frame(2)
        panel = (0, 0, 330, 110)  # top-left statistics panel
        self.assertGreater(mean_abs_diff(a.crop(panel), b.crop(panel)), 4.0)
        ticker = (400, 150, 640, 192)  # date label + progress bar, bottom right
        t0, t1 = with_stats.render_frame(0).crop(ticker), with_stats.render_frame(8).crop(ticker)
        self.assertGreater(mean_abs_diff(t0, t1), 0.5)  # the ticker advances through the year
        self.assertGreater(with_stats.stats.total, 1000)

    def test_hidden_by_default(self):
        self.assertFalse(small_settings().show_stats)


if __name__ == "__main__":
    unittest.main()
