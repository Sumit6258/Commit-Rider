"""Developer helper: contact sheet of rider close-ups at interesting moments of the ride."""
import sys

sys.path.insert(0, "src")
from PIL import Image, ImageDraw

from commit_rider.config.settings import Settings
from commit_rider.data.demo import generate_demo_series
from commit_rider.rendering.renderer import Renderer

theme = sys.argv[1] if len(sys.argv) > 1 else "midnight"
extra = dict(a.split("=") for a in sys.argv[2:])
s = Settings.from_mapping({"theme": theme, **extra})
r = Renderer(generate_demo_series(), s)
tl = r.timeline
picks = []
for f in tl.plan.flights[:2]:
    for dk in (-4, -1, 1, 3, 5, 7):
        pass
# choose frames: scan for characteristic states
def find(pred, skip=0):
    hits = [k for k in range(tl.frames) if pred(tl.frame(k))]
    return hits[skip] if len(hits) > skip else None
cands = [
    ("flat", find(lambda f: abs(f.pitch) < 0.05 and not f.airborne and f.controls.stand < 0.2)),
    ("climb", find(lambda f: f.pitch > 0.35 and not f.airborne)),
    ("descent", find(lambda f: f.pitch < -0.35 and not f.airborne)),
    ("airborne", find(lambda f: f.airborne and f.air_height > 20)),
    ("airborne2", find(lambda f: f.airborne and f.air_height > 20, 8)),
    ("landing", find(lambda f: f.controls.compress > 0.6 and not f.airborne)),
    ("wheelie", find(lambda f: f.controls.wheelie > 0.9)),
    ("flip", find(lambda f: f.airborne and abs(f.pitch) > 3.0)),
]
cands = [(n, k) for n, k in cands if k is not None]
tw, th = 300, 230
cols = 4
rows = (len(cands) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * th), (30, 30, 30))
for i, (name, k) in enumerate(cands):
    fr = tl.frame(k)
    img = r.render_frame(k)
    cx = int((fr.rear[0] + 52 - fr.cam_x) * r.unit)
    cy = int(r.sprites.anchor_px - (fr.rear[1] + 40 - fr.cam_y) * r.unit)
    crop = img.crop((cx - tw // 2, cy - th // 2, cx + tw // 2, cy + th // 2))
    d = ImageDraw.Draw(crop)
    d.text((6, 4), f"{name} k={k}", fill=(255, 255, 255))
    sheet.paste(crop, ((i % cols) * tw, (i // cols) * th))
sheet = sheet.resize((sheet.width * 3 // 2, sheet.height * 3 // 2), Image.Resampling.LANCZOS)
sheet.save(f"/tmp/sheet_{theme}.png")
print([(n, k) for n, k in cands], sheet.size)
