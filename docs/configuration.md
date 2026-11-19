# Configuration reference

Every option exists in four places with the same meaning: the Python `Settings` object, a command-line flag, a
GitHub Action input and a key in a JSON config file. Defaults are chosen so that **no option is required**.

## Appearance and animation

| Setting | CLI flag | Action input | Default | Values |
|---|---|---|---|---|
| `theme` | `--theme` | `theme` | `midnight` | `midnight`, `forest`, `sunset`, `neon`, `snow`, `minimal`, `monochrome`, or a custom theme |
| `bike` | `--bike` | `bike` | `bmx` | `bmx` (a single, polished bike; the architecture supports more) |
| `width` | `--width` | `width` | `1200` | 320 to 2400 pixels |
| `height` | `--height` | `height` | `360` | 96 to 900 pixels (the scene is authored at 360 and scales) |
| `fps` | `--fps` | `fps` | `18` | 5 to 30 |
| `duration` | `--duration` | `duration` | `8` | 2 to 30 seconds for one full lap |
| `ride_mode` | `--ride-mode` | `ride-mode` | `normal` | `normal`, `speed`, `stunt`, `relaxed` |
| `terrain_mode` | `--terrain-mode` | `terrain-mode` | `natural` | `natural`, `rolling`, `ramps`, `mountain`, `arcade` |
| `speed` | `--speed` | `speed` | `1.0` | 0.4 to 2.0 (multiplies the ride mode's ground speed) |
| `height_sensitivity` | `--height-sensitivity` | `height-sensitivity` | `1.0` | 0.3 to 2.0 (how tall hills grow) |
| `smoothing` | `--smoothing` | `smoothing` | `0.5` | 0 to 1 (terrain smoothing) |
| `stunt_intensity` | `--stunt-intensity` | `stunt-intensity` | mode default | 0 to 1; overrides the ride mode |
| `scaling` | `--scaling` | `scaling` | `log` | `log`, `sqrt`, `linear`, `rank` |
| `particles` | `--particles` / `--no-particles` | `particles` | `true` | dust and spray |
| `show_stats` | `--show-stats` / `--no-show-stats` | `show-stats` | `false` | statistics overlay and date ticker |
| `quality` | `--quality` | `quality` | `standard` | `draft` (1x, fast, jagged), `standard` (2x), `high` (3x supersampling) |
| `max_size_mb` | `--max-size-mb` | `max-size-mb` | `8` | 0.2 to 100 MiB (1 MiB = 1,048,576 bytes); see [file size](#file-size) |
| `seed` | `--seed` | `seed` | `0` | integer; varies decorations (trees, clouds, grass). The terrain itself depends only on your data |
| `bike_color` | `--bike-color` | `bike-color` | theme | `#rgb` or `#rrggbb` |
| `rider_color` | `--rider-color` | `rider-color` | theme | jersey colour |
| `terrain_color` | `--terrain-color` | `terrain-color` | theme | terrain and trail tint |
| `background_color` | `--background-color` | `background-color` | theme | sky colour (replaces the gradient and haze) |

Hard limits (`width x height x frames` and the total frame count) protect runners from accidental or hostile
settings. An invalid value is reported with the allowed range and *all* problems at once.

### Ride modes

| Mode | Ground speed | Default stunt intensity | Character |
|---|---|---|---|
| `normal` | x1.0 | 0.35 | Natural jumps, usually one wheelie |
| `speed` | x1.3 | 0.25 | Faster, the track scrolls by quickly |
| `stunt` | x1.0 | 0.95 | Big air from take-off pops, wheelies, backflips (only when the rider's head will clear the ground) |
| `relaxed` | x0.8 | 0.10 | Slow cruise, very few jumps |

Speed changes how many world units one day occupies (14 units at normal speed), so a faster ride is a longer
track covered in the same time. The lap always lasts exactly `duration` seconds and loops.

### Terrain modes

| Mode | Effect |
|---|---|
| `natural` | Rolling hills (default) |
| `rolling` | Lower, smoother, wider hills |
| `ramps` | Gradual run-ups with abrupt lips, so more jumps |
| `mountain` | Tall, peaky mountain trail |
| `arcade` | Stepped plateaus, one per activity level |

## Data

| Setting | CLI flag | Action input | Default | Meaning |
|---|---|---|---|---|
| source | `--source` | `source` | inferred | `github`, `demo` (offline, synthetic), `json`. The CLI infers `json` from `--input-json` and `github` from `--username` |
| username | `-u/--username` | `username` | repository owner (Action) | GitHub login (letters, digits, hyphens) |
| days | `--days` | `days` | `365` | 7 to 1100 most recent days (for JSON: the last N days of the file) |
| from / to | `--from`, `--to` | (use `days`) | today (UTC) | `YYYY-MM-DD`; `--from` overrides `--days` |
| private count | `--include-private` | `include-private` | `false` | Report GitHub's aggregate private-contribution count (needs a `read:user` token) |
| token | `--token-env NAME` | `token` | built-in token | Environment variable to read (CLI); there is deliberately no `--token` flag |

Dates and counting use **UTC calendar days**. Ranges longer than 365 days are fetched in several requests.

### JSON input

`--input-json FILE` accepts any of these layouts (see [`examples/sample-contributions.json`](../examples/sample-contributions.json)):

```json
[{"date": "2026-01-01", "count": 3}, {"date": "2026-01-02", "count": 0}]
```

or `{"days": [...]}` / `{"contributions": [...]}`, a bare GitHub `contributionCalendar` object, or a complete
GraphQL response saved from the API (`contributionCount` is understood too). Missing dates inside the span
are treated as zero; duplicates, negative or fractional counts, impossible dates (such as 2026-02-29) and
invalid JSON are rejected with a clear message.

## Output and publishing (Action)

| Action input | Default | Meaning |
|---|---|---|
| `output` | `dist/commit-rider.gif` | GIF path, relative to the workspace |
| `preview` | `true` | Also write a PNG still next to the GIF |
| `theme-file` | | Path to a JSON file defining a custom theme |
| `publish-branch` | | Commit the GIF and PNG to this branch (created as an orphan branch if missing) |
| `publish-dir` | | Sub-directory of that branch |
| `publish-history` | `squash` | `squash` keeps one commit (force-with-lease); `keep` appends commits |
| `commit-message` | `Update Commit Rider animation` | Commit message used when publishing |
| `python-version` | `3.12` | Python used to run the generator |

Action outputs: `path`, `preview-path`, `total-contributions`, `frames`, `size-bytes`, `published`.

## Custom themes

A theme file is a JSON object. `name` is required; everything else is optional and inherited from `base`
(default `midnight`). Colours are `#rgb`/`#rrggbb`. Example:

```json
{
  "name": "bubblegum",
  "base": "sunset",
  "sky": [[0.0, "#ffd1f0"], [1.0, "#fff4fb"]],
  "jersey": "#6a00ff",
  "frame": "#00c2a8",
  "terrain_top": "#ff8bd3",
  "terrain_bottom": "#8a3b73",
  "terrain_edge": "#ffffff",
  "trail": ["#d8a0c8", "#ffc2e6", "#ff8bd3", "#ff4fb8", "#c4007a"]
}
```

Use it with `commit-rider --theme-file bubblegum.json` (or the Action's `theme-file`). Valid fields are the
fields of `Theme` in `src/commit_rider/rendering/themes.py`; unknown or malformed values are rejected.

## File size

The default ride is about 5.9 MB (5.6 MiB). GIF size grows with area, frame count and visual complexity. When the
result is above `max-size-mb`, the exporter retries with a smaller palette and a small colour tolerance
(255, 192, 128, 96 then 64 colours), keeps the smallest result and logs a warning if even that is too large.
To shrink a GIF further reduce `width`, `fps` or `duration`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Invalid usage or configuration (bad option, unknown theme, bad date range, no source given) |
| 3 | Bad contribution data (unreadable or invalid JSON, impossible dates, negative counts) |
| 4 | GitHub error (missing/invalid token, permission, user not found, rate limit, network) |
| 5 | Rendering or output error (output not writable, not a `.gif`, validation failed) |
| 6 | Publishing to a git branch failed |
| 130 | Interrupted |

## For tools and a future web configurator

`commit-rider --print-schema` prints every setting with its type, range and default as JSON
(`commit_rider.config.settings.option_schema()`), and `Settings.from_mapping` / `Settings.to_dict` convert
loosely typed input (including Action-style strings) to and from the validated object. A web page could
therefore collect a username, bike, theme and options and generate the workflow YAML above without any change
to the engine.
