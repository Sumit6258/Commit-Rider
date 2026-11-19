# Installation guide

This guide assumes you have a GitHub account and **no** experience with GitHub Actions. It takes about
five minutes. (Running Commit Rider on your own machine is covered at the end.)

## 1. Create your profile repository

GitHub shows a special repository on your profile page: the one named **exactly like your username**.

1. Go to <https://github.com/new>.
2. Name it `USERNAME/USERNAME` (for example `Sumit6258/Sumit6258`), make it **public** and tick
   *Add a README file*.

Commit Rider itself lives in its own repository (`Sumit6258/commit-rider`). Your profile repository only
contains a small workflow that *uses* it; nothing is copied.

> If you already have a profile repository, use it. Commit Rider only adds one workflow file and a separate
> `output` branch; it never touches your existing files.

## 2. Add the workflow

1. In your profile repository choose **Add file → Create new file**.
2. Name it `.github/workflows/commit-rider.yml` (typing the `/` creates the folders).
3. Paste the contents of [`examples/workflows/commit-rider.yml`](../examples/workflows/commit-rider.yml):

```yaml
name: Generate Commit Rider

on:
  workflow_dispatch:          # lets you run it by hand from the Actions tab
  schedule:
    - cron: "15 0 * * *"      # and every day at 00:15 UTC

permissions:
  contents: write             # needed to push the GIF to the "output" branch

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - name: Check out the repository (provides the credentials used for publishing)
        uses: actions/checkout@v6

      - name: Generate and publish Commit Rider
        uses: Sumit6258/commit-rider@v1
        with:
          username: ${{ github.repository_owner }}
          output: dist/commit-rider.gif
          theme: midnight
          bike: bmx
          width: 1200
          height: 360
          fps: 18
          duration: 8
          publish-branch: output
```

4. Commit it to the default branch.

## 3. Run it once

Open the **Actions** tab, choose **Generate Commit Rider** in the left list and press **Run workflow**.
The first run takes a minute or two (it installs Python and Pillow, renders 144 frames and publishes).
When it finishes, your repository has a new branch called **`output`** containing `commit-rider.gif` and
`commit-rider.png`.

## 4. Show it on your profile

Edit your profile `README.md` and add (replace `USERNAME`):

```markdown
## 🚴 My GitHub Commit Rider

![Commit Rider](https://raw.githubusercontent.com/USERNAME/USERNAME/output/commit-rider.gif)
```

The URL has the shape `https://raw.githubusercontent.com/OWNER/REPO/BRANCH/FILE`, so the same works for any
repository: just change `OWNER/REPO` and the branch. GitHub serves README images through a caching proxy, so
a fresh animation can take a few minutes to appear.

## 5. Daily updates

The `schedule` trigger refreshes the animation every day. Things to know:

- Scheduled workflows run only from the repository's **default branch**.
- GitHub may disable scheduled workflows in a public repository after about 60 days without repository
  activity. If that happens, open the Actions tab and re-enable the workflow (or run it by hand).
- Times are UTC and can be delayed by GitHub during busy periods.

## Choosing a look

Change the `with:` block, for example:

```yaml
        with:
          theme: neon          # midnight, forest, sunset, neon, snow, minimal, monochrome
          ride-mode: stunt     # normal, speed, stunt, relaxed
          terrain-mode: ramps  # natural, rolling, ramps, mountain, arcade
          show-stats: true     # overlay total, best day, average, streak
          bike-color: "#ff3366"
```

Every option is listed in [configuration.md](configuration.md).

## Tokens and permissions

GitHub's GraphQL API requires an authenticated request, even for public data. What you need depends on
what you want to show.

| Mode | Token | Workflow `permissions` | Notes |
|---|---|---|---|
| **Public contributions** | The built-in `GITHUB_TOKEN` (the Action's default: you set nothing) | `contents: write` if you publish with `publish-branch`, otherwise `contents: read` | Shows your public contribution calendar |
| **Plus private contribution count** | A **classic** personal access token with the **`read:user`** scope, stored as a secret and passed as `token:` | as above | Adds GitHub's aggregate count of contributions that are not visible per day. Drawn as a number only (`include-private: true`, shown with `show-stats`), never spread over days |
| **No token / offline** | None | none | `source: demo` or the CLI's `--source demo` uses synthetic data |

**What has been verified, and how.** From GitHub's GraphQL reference: `contributionsCollection(from, to)` takes
a time range (defaulting to one year); the calendar's `contributionDays` carry a `date` and a
`contributionCount`; contributions in private and internal repositories are included only with the optional
`read:user` scope; and `restrictedContributionsCount` is the count of contributions the viewer cannot see,
non-zero only when the user chose to share private contribution counts. The widely used snake-animation
project reads the same calendar with the built-in token, which is the basis for the "no setup" public mode.
Commit Rider requests ranges of at most 365 days per call and merges longer ranges. **The author's build
environment had no network access, so none of this was exercised against the live API;** the client is
tested against a scripted transport and a local HTTP server. Run `commit-rider --username YOUR_NAME` once with
your own token and compare the total with your profile before relying on it (see
[releasing.md](releasing.md)). Fine-grained personal access tokens have not been verified for private
contribution counts; use a classic token.

### Creating the private-count token (optional)

1. GitHub → your avatar → **Settings → Developer settings → Personal access tokens → Tokens (classic) →
   Generate new token (classic)**.
2. Give it a name such as `commit-rider`, set an expiry, tick **only `read:user`**.
3. Copy the token once, then in your profile repository: **Settings → Secrets and variables → Actions →
   New repository secret**, name `COMMIT_RIDER_TOKEN`, paste, save.
4. In the workflow add `token: ${{ secrets.COMMIT_RIDER_TOKEN }}` and `include-private: true`
   (see [`examples/workflows/commit-rider-private.yml`](../examples/workflows/commit-rider-private.yml)).

Never put a token in a workflow file, the README or an issue. If one leaks, revoke it immediately.

### Repository settings that might get in the way

- **Actions must be enabled** (Settings → Actions → General).
- If you restrict actions to *"Allow actions created by GitHub"*, also allow `Sumit6258/commit-rider@*`
  (the workflow uses `actions/checkout`, `actions/setup-python` and `Sumit6258/commit-rider`).
- An explicit `permissions:` block in the workflow (as in the example) takes precedence over the repository's
  default workflow permissions. If an *organisation* caps the token at read-only, publishing will fail with a
  permission error; ask an owner to allow write access for this repository.
- `actions/checkout` must keep its credentials (its default, `persist-credentials: true`), because the
  publish step pushes with them. Do not set `persist-credentials: false` for this job.

## What publishing does (and does not do)

With `publish-branch: output` the Action, after generating the files:

1. fetches the branch (if it exists) and creates it as an **orphan** branch otherwise, so it shares no history
   with your code and never appears in your normal history;
2. copies **only** the generated `commit-rider.gif` and `commit-rider.png` into it (or into `publish-dir`);
   **any other files already on that branch are kept**: it never replaces the branch's contents;
3. commits only if something actually changed, as `github-actions[bot]`;
4. pushes. With the default `publish-history: squash` the branch holds a single commit, replaced with
   `--force-with-lease` pinned to the commit it just fetched, so a push by anyone else in the meantime is
   never overwritten (it retries from the new tip). **Why:** the animation changes every day and a GIF does
   not delta-compress, so appending ~6 MB commits daily would add roughly 2 GB per year. Use
   `publish-history: keep` if you prefer a normal, growing history.

Your other branches, your files and your working tree are never touched. Publishing to a different place
(GitHub Pages, S3, a release asset, an artifact) is up to you: leave out `publish-branch` and use the output
path `steps.<id>.outputs.path` in a later step.

## Pinning for maximum security

`@v1` follows the latest `1.x` release. To pin an exact version, use a tag (`@v1.0.0`) or, strongest, a full
commit SHA:

```bash
gh api repos/Sumit6258/commit-rider/git/ref/tags/v1.0.0 --jq .object.sha
```

```yaml
- uses: Sumit6258/commit-rider@<that-40-character-sha>   # v1.0.0
```

Dependabot (`package-ecosystem: github-actions`) can then keep the pin current. This repository's own
workflows use only GitHub's `actions/*` actions at their current major versions and no third-party action.
(The publishing step is built in, so you do not need a third-party "publish to branch" action.)

## Running on your own machine

```bash
python -m pip install "git+https://github.com/Sumit6258/commit-rider.git@v1.0.0"
export GITHUB_TOKEN=...                       # a personal access token (see "Tokens and permissions")
commit-rider --username YOUR_NAME --output dist/commit-rider.gif
commit-rider --source demo --theme neon --output dist/demo.gif      # offline, no token
```

Use `-vv` for detailed (redacted) logs. Exit codes are documented in [configuration.md](configuration.md#exit-codes).
