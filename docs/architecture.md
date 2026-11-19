# Architecture

Commit Rider is a small pipeline of independent stages. Each stage has one responsibility, a plain data
interface and its own tests.

```
GitHub API / JSON / demo data
        |  github/  data/        retrieval, validation, normalisation
        v
 ContributionSeries (contiguous UTC days)
        |  terrain/              counts -> heights -> smooth, loopable height field
        v
      Terrain
        |  animation/            physics, stunts, kinematics, rider rig, camera, particles
        v
      Timeline  (frame(k) is a pure, cheap function)
        |  rendering/            background, terrain strip, sprites, overlay
        v
   RGB frames
        |  rendering/exporter    global palette, inter-frame transparency, validation
        v
 commit-rider.gif (+ PNG)        pipeline.py ties these together; cli.py / action.py are the front ends
```

| Package / module | Responsibility |
|---|---|
| `github/graphql.py`, `client.py`, `parser.py` | The aggregate-only query and date windows; HTTP, retries, error mapping; response validation |
| `data/` | `ContributionDay/Series` models, input validation, normalisation (sort, gap fill, clip), statistics, deterministic demo data |
| `terrain/scaling.py` | Count to level mapping |
| `terrain/interpolation.py` | Gaussian smoothing, periodic PCHIP, Lipschitz rate limiting |
| `terrain/generator.py`, `geometry.py` | Build the height field; `Terrain` queries (height, slope, day under x) |
| `animation/physics.py` | Wheel contact: offset curve and two-wheel solve |
| `animation/stunts.py` | Jump, wheelie and flip planning; rider posture controls |
| `animation/movement.py` | Speed, time, wheel spin, crank angle, loop closure |
| `animation/bicycle.py`, `cyclist.py` | Bike geometry; rider skeleton and inverse kinematics |
| `animation/camera.py`, `particles.py` | Camera; dust as pure functions of time |
| `animation/engine.py` | `Timeline`: plans one lap, evaluates any frame |
| `rendering/themes.py`, `colors.py` | Theme data and colour helpers |
| `rendering/background.py`, `terrain_layer.py`, `sprites.py`, `overlay.py`, `renderer.py` | Drawing |
| `rendering/exporter.py` | GIF encoding and validation |
| `pipeline.py`, `sources.py`, `publish.py` | Orchestration, data sources, publishing to a branch |
| `cli.py`, `action.py` | Front ends (command line; GitHub Action) |
| `config/` | Defaults, limits, the validated `Settings` object |

## Terrain: counts to heights

1. **Scale** (`scaling.py`). For the default `log` method, `f(c) = ln(1 + c)`, `reference = p90` of the
   *non-zero* counts, and `u = f(c) / f(reference)`. Up to the reference, `level = u`. Above it,
   `level = 1 + 0.35 * tanh((u - 1) / 0.35)`, a soft shoulder: exceptional days become peaks and ramps
   (never more than 1.35) instead of being clipped or dominating. Zero days are level 0 (valleys). All-zero
   input is a flat valley; identical non-zero counts are a flat mid-height plain; one active day is the one
   hill.
2. **Close the loop.** A 16-day *bridge* eases from the last level down to a shallow valley and up to the
   first level, so the sequence is smooth as a circle.
3. **Smooth.** Circular Gaussian, `sigma = (1.0 + 1.6 * smoothing) * mode.sigma` days (default 1.8 days).
4. **Auto-contrast.** If the tallest hill is below 0.75 (sparse accounts: smoothing spreads a lone busy day
   thin), every level is multiplied by the same factor, at most 2.5, so the profile stays visible. Relative
   heights are unchanged and dense data gets a factor of exactly 1.
5. **Height.** `h = 22 + 112 * sensitivity * mode.amplitude * level^gamma` world units.
6. **Interpolate** with a periodic **PCHIP** (monotone cubic Hermite): C1, passes through every control
   point and never overshoots, so a spike between two zero days cannot dig a pit beside itself (a natural
   cubic spline would).
7. **Natural variation.** Two sine waves with whole-number cycles per lap add +-2.5 and +-1.4 units of relief,
   so long zero stretches are not a ruler-straight line, yet the loop stays exact.
8. **Round and limit.** A light Gaussian rounds corners; `|dh/dx| <= 1.0` is *guaranteed* by averaging the
   lower and upper Lipschitz cone envelopes (exact, O(n), no iteration), followed by a smoothing that cannot
   raise the maximum slope.

Everything is a pure function of the data and parameters, so identical input gives identical geometry.

### Why a percentile reference? An evaluation

Measured on the bundled **synthetic** demo year (301 active days, one added 5000-commit day):

| Method | Ordinary days' level shift when a 5000-commit day is added | Active days that are nearly flat (< 0.15) | Tallest day / median active day | Pearson r (count, level) |
|---|---|---|---|---|
| **log** (default) | **0.000** | 0.0 % | 2.0x | 0.77 |
| sqrt | 0.000 | 0.0 % | 2.1x | 0.80 |
| linear | 0.000 | 14.3 % | 3.4x | 0.79 |
| rank (ignores magnitude) | 0.001 | 0.0 % | 1.9x | 0.70 |
| log normalised by the **maximum** (no percentile) | **0.222** | | | |

With the maximum as the reference, one huge day lowers every other day by 22 % of the height range; with a
percentile reference it changes them by nothing. `linear` flattens a seventh of the active days under the
tall ones, and `rank` discards how *much* you contributed. `log` and `sqrt` are the best pair; `log`
keeps differences between small days (1 versus 2 commits) visible, hence the default. This is a measurement
on synthetic data, not a claim about every real profile; all four methods are selectable (`scaling`).

## Physics: how the bicycle follows the ground

*Wheel contact.* A wheel of radius `r` on a height field rests on the highest point of the terrain inside
its circle, so its centre height is `max over x' of h(x') + sqrt(r^2 - (x'-x)^2)`: the **offset curve**,
precomputed once. For the rigid wheelbase `W`, the two wheel centres are the points on that curve that are
`W` apart (a bisection per position). The bicycle's pitch is the direction between them, wheels cannot
penetrate the terrain (tested: worst measured penetration 0.009 units), and sharp valleys correctly produce
a corner in the wheel path.

*Jumps.* A **lip** is a place where a steep climb (slope >= 0.34 - 0.14 I) suddenly levels off or drops
(slope change >= 0.58 - 0.24 I, `I` = stunt intensity). From the lip the bike follows a true parabola with
constant "gravity" until it meets the ground path again; its pitch eases from the launch slope to the landing
slope so it lands wheels-down on the slope. No jumps are allowed near the loop seam. Landing absorption is
a smooth impulse response (rider crouch and fork compression).

*Stunts.* Wheelies are placed on long gentle stretches. Backflips (stunt mode only) are planned only if the
bike can leave the lip with a bigger pop, stay in the air long enough and, checked against the *real terrain
heights* along the whole rotation, the rider's head never gets within 19.5 units of the ground (the head
hangs ~130 units below the bike when inverted). Otherwise it is an ordinary jump. For very high air the
camera rises (see below).

*Rider.* Hip position, torso lean, arm bend and standing/crouching are smooth functions of the terrain slope,
the flight state and the landing response; two-bone inverse kinematics then places knees and elbows so that
hands stay on the grips and feet on the pedals in every pose (tested over 4,608 control combinations, no limb
ever fully extended). Every posture control is rate-limited to change by at most 0.45 between two frames, at
any frame rate, so the rider never "pops".

## Kinematics, time and the seamless loop

All quantities live on the terrain's spatial grid (1 unit) and are mapped to time by integrating
`dx / speed`, where the relative speed is 1 - 0.5 sin(pitch), clamped to 0.72..1.28 and smoothed; time is then
scaled so one lap lasts exactly `duration`. A frame is a cheap interpolation: `Timeline.frame(k)` has no
state, so frames are independent and `frame(frames)` equals `frame(0)` one lap later.

For the loop to be seamless, everything that repeats must close:

| Quantity | How it closes |
|---|---|
| Track | The closing bridge; the lap starts in the middle of it |
| Bicycle state | The lap starts and ends in the bridge, where jumps are forbidden |
| Wheel rotation | Total spin is snapped (< 0.1 %) to a whole number of spoke spacings |
| Crank angle | In the air the cranks glide to the next level position and stop; the (< half turn) difference to a whole number of turns is spread over the flight-free end of the lap |
| Camera | A pure function of the rider's position along the periodic track |
| Parallax layers | Each tile is `parallax * lap_length` wide, so one lap scrolls exactly one tile |
| Weather, twinkle | Whole numbers of cycles per loop |
| Dust | Pure functions of time; a puff alive at the end continues at the start |

Verified: the frame after the last is **byte-identical** to the first, and the change from last to first is
the same size as any other consecutive pair.

## Rendering and export

Scenery is drawn once into wide tiles or a terrain strip at 2x resolution and only cropped per frame.
Sprites are drawn per frame into tight local layers at **4x** and box-filtered down (Pillow snaps shapes to
whole pixels; supersampling is what keeps sub-pixel motion smooth). Fast wheels are drawn as faint
motion-blurred sweeps with a trace of spokes, because at 18 fps a wheel turns tens of degrees per frame and
crisp spokes would strobe.

The exporter builds one median-cut palette for the whole animation (with the rider and bike colours added
verbatim), maps frames without dithering, marks unchanged pixels transparent (disposal 1) so LZW can almost
ignore the sky, and lets Pillow's C encoder do the compression, assembling the GIF container itself. The
result is verified by reopening it (size, frames, timing, infinite loop, no blank frames) and a round-trip
test proves that decoding returns exactly the quantised frames. Typical performance on the build machine: about 50 ms per frame, about 10 s for the default animation (a 5.9 MB GIF).

## Testing

`tests/unit` (pure logic), `tests/rendering` (pixel-level checks of real renders), `tests/integration` (CLI,
Action entry point, git publishing against real local repositories, full pipeline). Notable invariants: no
wheel penetration; loop closure; wheel rotation equals distance travelled; pose never pops; head clears the
ground in flips; terrain drawn where the geometry says; no clipping; sprite colours do not blend into the
backdrop; the same input gives the same bytes. The GitHub client is tested against a scripted transport and a
real local HTTP server.

## Extending

- **A theme** is data: add a `Theme(...)` to `themes.py` or ship a JSON file. No algorithm changes.
- **A terrain mode** is a `TerrainMode` entry in `config/defaults.py`; **a ride mode** a `RideMode`.
- **A bicycle** needs a `BikeSpec` (geometry) in `animation/bicycle.py`, an entry in `BIKES` and `config/defaults.BIKES`,
  and drawing in `rendering/sprites.py`.
- **A configuration website** can use `option_schema()` and `Settings.from_mapping`; no engine change.
