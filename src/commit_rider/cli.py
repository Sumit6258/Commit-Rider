"""Command-line interface: ``commit-rider`` / ``python -m commit_rider``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from commit_rider import __version__
from commit_rider.config.settings import Settings, option_schema
from commit_rider.errors import CommitRiderError, ConfigError
from commit_rider.logging_utils import configure, redact, register_secret
from commit_rider.pipeline import GenerationResult, generate
from commit_rider.rendering.themes import THEMES, load_theme_file
from commit_rider.sources import SOURCES, TOKEN_ENV_VARS, DataRequest, load_series, resolve_token

log = logging.getLogger("commit_rider")

_VALUE_OPTIONS = (
    "theme", "bike", "width", "height", "fps", "duration", "ride_mode", "terrain_mode", "speed",
    "height_sensitivity", "smoothing", "stunt_intensity", "quality", "max_size_mb", "seed",
    "scaling", "bike_color", "rider_color", "terrain_color", "background_color",
)
_BOOL_OPTIONS = ("particles", "show_stats")

EPILOG = """\
examples:
  commit-rider --username Sumit6258 --output dist/commit-rider.gif
  commit-rider --source demo --theme neon --output dist/demo.gif
  commit-rider --input-json examples/sample-contributions.json --output dist/custom.gif
  commit-rider --source demo --theme midnight --bike bmx --width 1200 --height 360 --fps 18 --duration 8

authentication:
  GitHub's GraphQL API needs a token even for public data. It is read from the environment
  (COMMIT_RIDER_TOKEN, GITHUB_TOKEN, then GH_TOKEN) or from the variable named by
  --token-env. There is deliberately no --token flag: command lines end up in shell history.
  Demo and JSON modes need no token.

exit codes:
  0 success   2 bad usage or configuration   3 bad contribution data
  4 GitHub error (auth, user not found, rate limit, network)   5 render or output error
"""


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date in YYYY-MM-DD form") from None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="commit-rider",
        description="Turn your GitHub contributions into an animated bicycle ride over contribution terrain.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"commit-rider {__version__}")
    src = p.add_argument_group("data source")
    src.add_argument("--source", choices=SOURCES, help="github (needs --username and a token), demo (offline, synthetic) or json")
    src.add_argument("-u", "--username", help="GitHub username (implies --source github)")
    src.add_argument("--input-json", type=Path, metavar="FILE", help="read daily counts from a JSON file (implies --source json)")
    src.add_argument("--days", type=int, help="number of most recent days to ride (default 365; for JSON, the last N days)")
    src.add_argument("--from", dest="start", type=_date, metavar="DATE", help="first day, YYYY-MM-DD (overrides --days)")
    src.add_argument("--to", dest="end", type=_date, metavar="DATE", help="last day, YYYY-MM-DD (default: today UTC)")
    src.add_argument("--include-private", action="store_true", help="also report GitHub's aggregate count of private contributions (needs a token with read:user)")
    src.add_argument("--token-env", metavar="NAME", help="read the token from this environment variable")

    out = p.add_argument_group("output")
    out.add_argument("-o", "--output", type=Path, default=Path("dist/commit-rider.gif"), help="GIF to write (default: %(default)s)")
    out.add_argument("--preview", type=Path, metavar="PNG", help="PNG preview path (default: next to the GIF)")
    out.add_argument("--no-preview", action="store_true", help="do not write a PNG preview")
    out.add_argument("--max-size-mb", help="soft GIF size limit; quality is reduced step by step to fit (default 8)")

    look = p.add_argument_group("appearance and animation")
    look.add_argument("--theme", help="midnight, forest, sunset, neon, snow, minimal, monochrome (default midnight)")
    look.add_argument("--theme-file", type=Path, metavar="FILE", help="JSON file defining a custom theme (see docs/configuration.md)")
    look.add_argument("--bike", help="bicycle style (only 'bmx' for now)")
    look.add_argument("--width", help="pixels (default 1200)")
    look.add_argument("--height", help="pixels (default 360)")
    look.add_argument("--fps", help="frames per second, 5-30 (default 18)")
    look.add_argument("--duration", help="seconds for one full lap, 2-30 (default 8)")
    look.add_argument("--ride-mode", help="normal, speed, stunt or relaxed")
    look.add_argument("--terrain-mode", help="natural, rolling, ramps, mountain or arcade")
    look.add_argument("--speed", help="ground speed multiplier, 0.4-2.0 (default 1.0)")
    look.add_argument("--height-sensitivity", help="how tall hills grow, 0.3-2.0 (default 1.0)")
    look.add_argument("--smoothing", help="terrain smoothing, 0-1 (default 0.5)")
    look.add_argument("--stunt-intensity", help="0-1; overrides the ride mode's default")
    look.add_argument("--scaling", help="count-to-height mapping: log, sqrt, linear or rank (default log)")
    look.add_argument("--quality", help="draft, standard or high (default standard)")
    look.add_argument("--seed", help="integer seed for decorative variation (default 0)")
    look.add_argument("--bike-color", metavar="HEX", help="frame colour, e.g. #ff3366")
    look.add_argument("--rider-color", metavar="HEX", help="jersey colour")
    look.add_argument("--terrain-color", metavar="HEX", help="terrain colour")
    look.add_argument("--background-color", metavar="HEX", help="sky colour")
    look.add_argument("--particles", action=argparse.BooleanOptionalAction, default=None, help="dust and spray (default on)")
    look.add_argument("--show-stats", action=argparse.BooleanOptionalAction, default=None, help="statistics overlay (default off)")
    look.add_argument("--config", type=Path, metavar="FILE", help="JSON file with any of the settings above (flags override it)")

    misc = p.add_argument_group("information")
    misc.add_argument("--list-themes", action="store_true", help="list themes and exit")
    misc.add_argument("--print-schema", action="store_true", help="print all settings as JSON and exit")
    misc.add_argument("-v", "--verbose", action="count", default=0, help="more logging (-vv for debug)")
    misc.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    return p


def _load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError("The config file must contain a JSON object")
    return data


def _settings(args: argparse.Namespace, theme_name: str | None) -> Settings:
    mapping = _load_config(args.config)
    for name in _VALUE_OPTIONS + _BOOL_OPTIONS:
        value = getattr(args, name, None)
        if value is not None:
            mapping[name] = value
    if theme_name and "theme" not in mapping:
        mapping["theme"] = theme_name
    return Settings.from_mapping(mapping)


def _request(args: argparse.Namespace) -> DataRequest:
    source = args.source
    if source is None:
        source = "json" if args.input_json else "github" if args.username else None
    if source is None:
        raise ConfigError("Choose a data source: --username NAME, --source demo, or --input-json FILE")
    token = None
    if source == "github":
        names = (args.token_env,) if args.token_env else TOKEN_ENV_VARS
        token = resolve_token(os.environ, names)
        register_secret(token)
    return DataRequest(
        source=source, username=args.username, token=token, input_json=args.input_json,
        days=args.days, start=args.start, end=args.end, include_private=args.include_private,
    )


def _report(result: GenerationResult, request: DataRequest, quiet: bool) -> None:
    if quiet:
        return
    series, rep, stats = result.series, result.report, result.stats
    who = f"GitHub user {series.username}" if request.source == "github" else (
        "synthetic demo data (not real contributions)" if request.source == "demo" else f"JSON file {request.input_json}")
    s = result.summary
    print("Commit Rider")
    print(f"  data    : {who}")
    print(f"            {stats.start} to {stats.end}  ({stats.days} days, {stats.total:,} contributions)")
    if stats.restricted:
        print(f"            +{stats.restricted:,} private contributions (aggregate; not drawn)")
    print(f"  ride    : {s['jumps']} jumps, {s['flips']} flips, {s['wheelies']} wheelies")
    print(f"  output  : {rep.path}  ({rep.size_mb:.2f} MiB, {rep.frames} frames, {rep.width}x{rep.height}, "
          f"{rep.duration_ms / 1000:.1f} s, loops forever)")
    if not rep.within_limit:
        print("  warning : above the size limit even at the lowest quality tried")
    if result.preview_path:
        print(f"  preview : {result.preview_path}")
    print(f"  done in {result.seconds:.1f} s")


def _run(args: argparse.Namespace) -> int:
    configure(args.verbose, args.quiet)
    if args.list_themes:
        for name, theme in THEMES.items():
            print(f"{name:12s} {theme.description}")
        return 0
    if args.print_schema:
        print(json.dumps(option_schema(), indent=2))
        return 0
    theme_name = load_theme_file(args.theme_file).name if args.theme_file else None
    settings = _settings(args, theme_name)
    request = _request(args)
    if request.source == "demo" and not args.quiet:
        print("Using synthetic demo data (not real contributions).", file=sys.stderr)

    series = load_series(request)
    last_pct = [-1]

    def progress(done: int, total: int) -> None:
        pct = done * 100 // total // 25 * 25
        if pct != last_pct[0] and args.verbose:
            last_pct[0] = pct
            log.info("rendering %d%%", pct)

    result = generate(
        series, settings, args.output,
        preview=False if args.no_preview else (args.preview or True),
        progress=progress,
    )
    _report(result, request, args.quiet)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    try:
        return _run(args)
    except CommitRiderError as exc:
        print(f"error: {redact(str(exc))}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception:  # noqa: BLE001 - last resort: show the traceback instead of hiding it
        traceback.print_exc()
        print("error: unexpected internal error (please report it, including the traceback above)", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
