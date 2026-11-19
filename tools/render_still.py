"""Developer helper: render one or more frames of the demo ride to PNG for inspection."""
import sys
import time

sys.path.insert(0, "src")
from commit_rider.config.settings import Settings
from commit_rider.data.demo import generate_demo_series
from commit_rider.rendering.renderer import Renderer

theme = sys.argv[1] if len(sys.argv) > 1 else "midnight"
frames = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [20]
extra = dict(a.split("=") for a in sys.argv[3:])
s = Settings.from_mapping({"theme": theme, **extra})
t0 = time.time()
r = Renderer(generate_demo_series(), s)
print(f"setup {time.time()-t0:.2f}s", r.timeline.summary())
for k in frames:
    t1 = time.time()
    img = r.render_frame(k)
    img.save(f"/tmp/still_{theme}_{k}.png")
    print(f"frame {k}: {time.time()-t1:.2f}s  {img.size}")
print("preview index", r.preview_index())
