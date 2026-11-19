import io
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from commit_rider.errors import OutputError
from commit_rider.rendering import exporter
from commit_rider.rendering.exporter import (
    _delays_cs,
    _palette_image,
    build_palette,
    encode_gif,
    export_gif,
    save_preview,
    validate_gif,
)


def make_frames(width=96, height=64, count=12, repeat_last=True):
    frames = []
    for k in range(count):
        im = Image.new("RGB", (width, height), (20, 30, 60))
        d = ImageDraw.Draw(im)
        d.rectangle((0, int(height * 0.62), width, height), fill=(60, 120, 60))
        d.ellipse((10 + k * 5, 10, 30 + k * 5, 30), fill=(250, 140, 40))
        d.line((0, 5 + k, width, height - 14 - k), fill=(200, 200, 255), width=2)
        frames.append(im)
    if repeat_last:
        frames.append(frames[-1].copy())  # an identical frame exercises the 1x1 patch path
    return frames


def gif_blocks(data: bytes):
    """Parse the GIF container into (header info, list of frame descriptors)."""
    assert data[:6] == b"GIF89a"
    width, height, packed = struct.unpack("<HHB", data[6:11])
    pos = 13 + (3 * (2 << (packed & 7)) if packed & 0x80 else 0)
    info = {"size": (width, height), "gct": bool(packed & 0x80), "loop": None, "frames": [], "netscape": 0}
    pending = {}
    while data[pos] != 0x3B:
        if data[pos] == 0x21:
            label = data[pos + 1]
            p = pos + 2
            blocks = []
            while data[p] != 0:
                blocks.append(data[p + 1 : p + 1 + data[p]])
                p += data[p] + 1
            if label == 0xFF and blocks and blocks[0] == b"NETSCAPE2.0":
                info["netscape"] += 1
                info["loop"] = struct.unpack("<H", blocks[1][1:3])[0]
            if label == 0xF9:
                flags, delay, transparent = blocks[0][0], struct.unpack("<H", blocks[0][1:3])[0], blocks[0][3]
                pending = {"disposal": (flags >> 2) & 7, "has_transparency": bool(flags & 1), "delay": delay, "transparent": transparent}
            pos = p + 1
        elif data[pos] == 0x2C:
            left, top, w, h, ipacked = struct.unpack("<HHHHB", data[pos + 1 : pos + 10])
            pending.update(rect=(left, top, w, h), local_table=bool(ipacked & 0x80), interlaced=bool(ipacked & 0x40))
            info["frames"].append(pending)
            pending = {}
            pos += 10
            pos += 1  # LZW min code size
            while data[pos] != 0:
                pos += data[pos] + 1
            pos += 1
        else:
            raise AssertionError(f"unexpected byte {data[pos]:#x}")
    return info


class EncoderTests(unittest.TestCase):
    def assert_roundtrip(self, frames, **kwargs):
        data, used = encode_gif(frames, 18, colors=64, **kwargs)
        im = Image.open(io.BytesIO(data))
        palette = _palette_image(build_palette(frames, 64))
        self.assertEqual(im.n_frames, len(frames))
        for k, frame in enumerate(frames):
            im.seek(k)
            expected = frame.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
            self.assertIsNone(ImageChops.difference(im.convert("RGB"), expected).getbbox(), f"frame {k}")
        return data

    def test_lossless_roundtrip_is_exact(self):
        self.assert_roundtrip(make_frames())

    def test_odd_sizes_roundtrip(self):
        for size in ((97, 33), (300, 20), (5, 5)):
            self.assert_roundtrip(make_frames(*size, count=4))

    def test_tolerance_mode_roundtrip_on_flat_art(self):
        self.assert_roundtrip(make_frames(), tolerance=4)

    def test_container_structure(self):
        frames = make_frames()
        data, _ = encode_gif(frames, 18, colors=64)
        info = gif_blocks(data)
        self.assertEqual(info["size"], (96, 64))
        self.assertTrue(info["gct"])
        self.assertEqual((info["netscape"], info["loop"]), (1, 0))  # loops forever, declared once
        self.assertEqual(len(info["frames"]), len(frames))
        self.assertTrue(all(not f["local_table"] for f in info["frames"]), "one global palette only")
        self.assertTrue(all(not f["interlaced"] for f in info["frames"]))
        self.assertTrue(all(f["disposal"] == 1 for f in info["frames"]))
        self.assertEqual(info["frames"][0]["rect"], (0, 0, 96, 64))
        self.assertFalse(info["frames"][0]["has_transparency"])
        self.assertTrue(all(f["has_transparency"] for f in info["frames"][1:]))
        self.assertEqual(info["frames"][-1]["rect"][2:], (1, 1))  # the identical frame costs 1 pixel
        self.assertLess(info["frames"][3]["rect"][2] * info["frames"][3]["rect"][3], 96 * 64)  # delta frames are cropped

    def test_delays_track_the_frame_rate(self):
        for fps in (5, 10, 15, 18, 20, 24, 30):
            delays = _delays_cs(fps * 4, fps)
            self.assertAlmostEqual(sum(delays), 400, delta=1, msg=fps)
            self.assertTrue(all(d >= 2 for d in delays))
        self.assertEqual(set(_delays_cs(36, 18)), {5, 6})

    def test_palette_is_shared_and_keeps_key_colours(self):
        frames = make_frames()
        keys = [(1, 2, 3), (250, 250, 5)]
        flat = build_palette(frames, 32, keys)
        entries = {tuple(flat[i : i + 3]) for i in range(0, 96, 3)}
        for key in keys:
            self.assertIn(key, entries)
        self.assertEqual(len(flat), 768)
        with self.assertRaises(ValueError):
            build_palette(frames, 1)
        with self.assertRaises(ValueError):
            build_palette(frames, 256)

    def test_input_validation(self):
        with self.assertRaises(OutputError):
            encode_gif([], 18)
        with self.assertRaises(OutputError):
            encode_gif([Image.new("RGB", (8, 8)), Image.new("RGB", (9, 8))], 18)
        with self.assertRaises(OutputError):
            encode_gif([Image.new("L", (8, 8))], 18)  # type: ignore[list-item]


class ExportAndValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_export_writes_and_validates(self):
        frames = make_frames(repeat_last=False)
        report = exporter.export_gif(frames, self.dir / "sub" / "dir" / "out.gif", 18, colors=64)
        self.assertTrue(report.path.exists())  # parent directories were created
        self.assertEqual((report.frames, report.width, report.height, report.loop), (12, 96, 64, 0))
        self.assertAlmostEqual(report.duration_ms, 12 * 1000 / 18, delta=25)
        self.assertEqual(report.attempts[0].split(",")[0], "64 colours")
        self.assertTrue(report.within_limit)

    def test_size_limit_triggers_progressively_cheaper_attempts(self):
        frames = make_frames(300, 120, count=10, repeat_last=False)
        with self.assertLogs("commit_rider", level="WARNING") as logs:
            report = export_gif(frames, self.dir / "tiny.gif", 18, colors=255, max_bytes=100)
        self.assertGreater(len(report.attempts), 2)
        self.assertFalse(report.within_limit)
        self.assertTrue(any("above" in line for line in logs.output))
        self.assertTrue(report.path.exists())  # still delivers the smallest result it found
        generous = export_gif(frames, self.dir / "ok.gif", 18, colors=255, max_bytes=10_000_000)
        self.assertEqual(len(generous.attempts), 1)

    def test_validate_gif_catches_problems(self):
        frames = make_frames(repeat_last=False)
        good = self.dir / "good.gif"
        export_gif(frames, good, 18, colors=64)
        validate_gif(good, expected_size=(96, 64), expected_frames=12, expected_fps=18)
        with self.assertRaises(OutputError):
            validate_gif(good, expected_size=(100, 64))
        with self.assertRaises(OutputError):
            validate_gif(good, expected_frames=11)
        with self.assertRaises(OutputError):
            validate_gif(good, expected_frames=12, expected_fps=5)  # timing mismatch
        with self.assertRaises(OutputError):
            validate_gif(self.dir / "missing.gif")
        png = self.dir / "x.png"
        Image.new("RGB", (4, 4)).save(png)
        with self.assertRaises(OutputError):
            validate_gif(png)
        once = self.dir / "once.gif"  # not looping
        frames[0].save(once, save_all=True, append_images=frames[1:], loop=3, duration=50)
        with self.assertRaises(OutputError):
            validate_gif(once)
        blank = self.dir / "blank.gif"
        blank_frames = [Image.new("RGB", (16, 16), (0, 0, 0)) for _ in range(4)]
        with self.assertRaises(OutputError):  # export validates its own output...
            export_gif(blank_frames, blank, 10, colors=8)
        self.assertFalse(blank.exists())  # ...and never leaves the broken file behind

    def test_unwritable_destinations(self):
        blocker = self.dir / "file.txt"
        blocker.write_text("x")
        with self.assertRaises(OutputError):
            export_gif(make_frames(count=3), blocker / "nested" / "out.gif", 10)
        with self.assertRaises(OutputError):
            save_preview(Image.new("RGB", (4, 4)), blocker / "p.png")

    def test_preview_png(self):
        path = save_preview(Image.new("RGB", (30, 10), (9, 9, 9)), self.dir / "p" / "preview.png")
        with Image.open(path) as im:
            self.assertEqual((im.format, im.size), ("PNG", (30, 10)))


if __name__ == "__main__":
    unittest.main()
