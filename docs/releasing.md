# Releasing and publishing

This page is for the maintainer. It lists what to verify against the real GitHub before the first release,
and the exact commands to publish.

## What was not verified before the first release

The code was developed and tested in an offline sandbox. Verify these on a real machine/runner and fix anything
that differs *before* tagging `v1.0.0`:

1. **Live API.** `commit-rider --username Sumit6258 --output dist/live.gif` with a real token. Compare the
   total printed ("N contributions") with your profile's graph for the same period (UTC days; private
   contributions only with `read:user`). Also try `--days 800` (two requests) and a nonexistent user.
2. **The Action on a hosted runner.** CI runs the Action from the checkout (`uses: ./`, job `action`); also try it
   from a scratch repository with `publish-branch: output` and confirm the branch appears with only the GIF
   and PNG. Check that the public mode works with the built-in `GITHUB_TOKEN` alone.
3. **CI matrix.** The first run of `.github/workflows/ci.yml` (Ubuntu and macOS, Python 3.11 to 3.13) has not
   been executed. The suite was run only on Linux with Python 3.12 and Pillow 13.0.0. `ruff` was not available
   offline; run `ruff check .` and fix anything it reports.
4. **Pinned versions.** `requirements.txt` pins Pillow 13.0.0 (the version the suite ran with); confirm it installs on
   the runner. The workflows reference `actions/checkout@v6` and `actions/setup-python@v6`.
5. **Coverage gate.** CI requires 85 % overall and 90 % for `terrain` plus `animation` (line coverage). The
   dependency-free `tools/linecov.py` measured 98.2 % overall and 98.8 % for those two packages on the final code;
   `coverage.py` counts slightly differently, so adjust the thresholds in `ci.yml` if the first run disagrees.

## Publishing the repository

Check the name is free first (do not overwrite anything):

```bash
gh auth status
gh repo view Sumit6258/commit-rider    # should say "Could not resolve to a Repository"
```

Then, from the project directory:

```bash
git init -b main
git add .
git status                              # review: no tokens, no dist/ output, nothing unexpected
git commit -m "Initial release"
gh repo create Sumit6258/commit-rider --public \
  --description "Your GitHub contributions. Your terrain. Your ride." \
  --source=. --remote=origin --push
```

Enable *private vulnerability reporting* (Settings → Code security) and add topics (`github-profile`,
`github-actions`, `animation`, `python`). Wait for CI on `main` to pass.

## Tagging

1. Set the date in `CHANGELOG.md` (`## [1.0.0] - YYYY-MM-DD`) and commit.
2. Create the tag only when CI is green:

```bash
git tag -a v1.0.0 -m "Commit Rider 1.0.0"
git push origin v1.0.0
```

The **Release** workflow checks that the tag matches `pyproject.toml`, runs the tests, builds the package,
creates the GitHub release and then moves the major tag `v1` to the same commit (the only force-push it does,
and only on that moving tag). Until `v1` exists, consumers can use `@main` or `@v1.0.0`.

## After the release

- Try the example workflow in a fresh repository using `Sumit6258/commit-rider@v1`.
- Do **not** touch your profile repository until you are satisfied; adding the workflow there is a separate step
  (see [installation.md](installation.md)).

## Versioning policy

Semantic versioning. `v1` moves to each new `1.x.y`; breaking changes (renamed inputs, changed defaults that
alter existing output meaningfully, dropped options) require `v2`. New options and themes are minor releases.
