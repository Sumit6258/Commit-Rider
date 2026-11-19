# Security policy

## Reporting a vulnerability

Please report security problems **privately** through GitHub's
[private vulnerability reporting](https://github.com/Sumit6258/commit-rider/security/advisories/new)
rather than a public issue. Include what you found, how to reproduce it and the version
(`commit-rider --version`). You will get an answer as soon as possible; please allow a reasonable time
to fix the problem before disclosing it.

## Supported versions

Only the latest `1.x` release (the `v1` tag) receives fixes.

## How Commit Rider handles secrets and untrusted input

- **Tokens** come from the environment (`COMMIT_RIDER_TOKEN`, `GITHUB_TOKEN`, `GH_TOKEN`) or the Action's
  `token` input. There is deliberately **no `--token` command-line flag** (command lines end up in shell
  history and process lists). A token is only ever placed in the `Authorization` header of an HTTPS
  request. It is never logged, never written to the GIF/PNG, never included in an exception message, and
  the Action registers it with `::add-mask::`. A redacting log filter additionally replaces anything that
  looks like a GitHub token (`ghp_…`, `github_pat_…`) before a record is emitted.
- **Data requested** is aggregate-only: daily contribution counts, the calendar total and GitHub's
  aggregate count of contributions that are not visible per day. The query never asks for repository
  names, commit messages or any other repository detail, so none can leak into an animation. The
  private-contribution count is shown only as a number and never spread across days.
- **Action inputs** are passed to the program as environment variables, never spliced into shell text,
  so an input value cannot inject shell commands.
- **Network:** HTTPS only (the client refuses other schemes), bounded timeouts, bounded retries.
  API responses are validated field by field before use.
- **Resource limits:** width, height, frame rate, duration, number of days and total rendering work are
  capped (see `docs/configuration.md`), so a hostile or mistaken input cannot exhaust a runner.
- **Publishing** runs `git` with argument lists (no shell), validates branch names and paths and only adds or
  updates the files it generated; other files on the publish branch are kept. By default the publish branch
  holds a single commit that is replaced with `--force-with-lease` pinned to the commit just fetched, so a
  concurrent push by anybody else is never overwritten (`publish-history: keep` never rewrites history).
- **Supply chain:** the runtime has a single dependency (Pillow), pinned exactly in `requirements.txt`
  for the Action. The workflows use only GitHub's own `actions/*` actions, at their current major
  versions, and no third-party actions. Dependabot is configured for both ecosystems. For maximum
  assurance, pin `actions/*` and `Sumit6258/commit-rider` to full commit SHAs in your own workflow, e.g.
  `gh api repos/Sumit6258/commit-rider/git/ref/tags/v1.0.0 --jq .object.sha`, and let Dependabot update them.

## Known limitations

- The built-in `GITHUB_TOKEN` is sufficient for *public* contributions. For private contribution counts
  you must provide a personal access token, which is a powerful credential: use a classic token with only
  the `read:user` scope and store it as a repository secret.
- Secrets are not passed to workflows triggered from forks. If the `token` input expands to an empty string
  the Action stops with a clear error instead of silently using a different credential; omit the input to use
  the built-in `GITHUB_TOKEN`.
