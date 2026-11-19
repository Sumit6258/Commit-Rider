# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/): the `v1` tag always points at the latest `1.x.y` release,
so `uses: Sumit6258/commit-rider@v1` receives fixes and features but never breaking changes.

## [1.0.0] - Unreleased

First release. (Set the date when the tag is created; see `docs/releasing.md`.)

### Added
- Terrain generator: daily counts to a smooth, deterministic, loopable trail (robust p90 scaling with a
  soft cap, periodic PCHIP interpolation, exact slope limit, closing bridge so the loop has no seam).
- Animation engine: wheel-contact physics on the terrain's offset curve, parabolic jumps from detected
  lips, wheelies, optional backflips with ground-clearance checks, landing absorption, rider rig with
  inverse kinematics, camera that follows the terrain and big air, deterministic dust particles.
- Seven themes (midnight, forest, sunset, neon, snow, minimal, monochrome), custom colours, custom
  theme files, five terrain modes, four ride modes, three quality presets, optional statistics overlay.
- GIF exporter: one global palette, inter-frame transparency, automatic size fitting, validation after
  writing, PNG preview.
- GitHub GraphQL client: aggregate data only, bounded retries with exponential backoff, rate-limit and
  authentication handling, secrets redaction, no third-party HTTP dependency.
- Command line interface (`commit-rider`, `python -m commit_rider`) with documented exit codes.
- Reusable composite GitHub Action with optional publishing to an orphan branch (no third-party
  publishing action; unrelated files preserved; single-commit history by default so a daily GIF does not
  bloat the repository, `publish-history: keep` to append commits).
- Test suite, CI workflow, release workflow, Dependabot configuration, documentation.
