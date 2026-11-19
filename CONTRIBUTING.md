# Contributing

Thanks for helping! Themes, bikes, terrain modes, documentation and bug reports are all welcome.

## Development setup

```bash
git clone https://github.com/Sumit6258/commit-rider.git
cd commit-rider
python -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"
```

Python 3.11 or newer. The only runtime dependency is Pillow; `pytest`, `pytest-cov`, `ruff`, `build` and
`PyYAML` are development tools.

## Checks

```bash
python -m pytest                                    # all tests (about a minute and a half)
python -m pytest tests/unit                         # fast logic tests only
ruff check .                                        # lint (pyproject.toml: E, F, W; line length is advisory)
python tools/lint_check.py                          # dependency-free fallback for unused imports and similar
python tools/linecov.py                             # dependency-free line coverage (Python 3.12+)
```

The tests are plain `unittest.TestCase` classes, so `python -m unittest discover -s tests -t .` also works.

## Making visual changes

Rendering is deterministic, so look at it:

```bash
commit-rider --source demo --output /tmp/demo.gif          # also writes /tmp/demo.png
python tools/render_still.py neon 20,60,85                  # individual frames to /tmp/still_*.png
python tools/contact_sheet.py midnight                      # close-ups of climbs, descents, jumps, wheelies
```

Check at full size and at roughly 830 px wide (a README column) and look for: jitter, limbs detached from
the bike, wheels leaving the frame, the bike sinking into the ground, poor contrast against the sky and a
visible seam where the loop restarts. If you change the look, regenerate `examples/` with
`python tools/make_examples.py` and mention it in the pull request.

## Adding things

- **Theme:** data only; see "Extending" in [docs/architecture.md](docs/architecture.md). Check contrast
  (`tests/rendering/test_renderer.py` fails if the rider blends into the backdrop).
- **Bicycle:** a new `BikeSpec`, drawing code in `rendering/sprites.py` and a test that the rider stays attached
  (`tests/unit/test_animation.py`). Please aim for the quality of the existing bike rather than adding several
  rough ones.
- **Option:** add it to `Settings` (validation, coercion, schema), the CLI, `action.yml` (input and env mapping),
  `docs/configuration.md` and the tests. `tests/unit/test_metadata.py` fails when these drift apart.

## Pull requests

- Keep changes focused; add or update tests; do not weaken a test to make it pass.
- No secrets, ever (a test scans for token-like strings). Do not log tokens.
- Do not fetch and execute external scripts or add a dependency without a strong reason.
- Update `CHANGELOG.md` under "Unreleased" for user-visible changes.

## Code of conduct

Be kind and constructive. Harassment is not tolerated.
