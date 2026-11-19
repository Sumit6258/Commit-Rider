# Troubleshooting

Run locally with `-vv` for detailed logs; the Action honours "Enable debug logging" (re-run the workflow
with it enabled). Tokens are redacted from all output.

| Message or symptom | Cause | Fix |
|---|---|---|
| `GitHub's GraphQL API requires an access token` | No token reached the program | Locally: `export GITHUB_TOKEN=...`. In the Action: omit `token:` to use the built-in token, or create the secret you reference (an unset secret expands to an empty string) |
| `GitHub rejected the token (HTTP 401)` | Token expired, revoked or mistyped | Create a new token and update the secret |
| `GitHub refused the request (HTTP 403)` / `Resource not accessible by integration` | The token cannot read this data | Use a classic token with `read:user`, or check organisation restrictions |
| `GitHub rate limit reached; it resets at ...` | Too many requests for this token | Wait until the reset time. One run makes 1 request per 365 days |
| `GitHub reports that this user does not exist` | Wrong `username` (note: it defaults to the repository *owner*, which may be an organisation) | Pass `username:` explicitly |
| `Could not reach GitHub` / `temporarily unavailable` | Network problem or a GitHub outage (retried 3 times with backoff) | Re-run later |
| Totals differ from the profile page | The calendar counts *eligible contributions in UTC days*, and private contributions only appear if your token and profile settings allow it | Compare the same UTC range; see `include-private` |
| Flat, boring terrain | Very few or very even contributions | Increase `height-sensitivity` (up to 2.0), or use `terrain-mode: mountain` |
| `The output file must end in .gif` / `not writable` | Bad `output` path | Use a writable path ending in `.gif` |
| `GIF is X MiB, above the Y MiB limit` (warning) | Large size/duration even at the lowest quality tried | Reduce `width`, `fps` or `duration` |
| Image in README does not update | GitHub proxies and caches README images; the workflow did not run; or it ran but nothing changed | Wait a few minutes; check the workflow's latest run; append `?v=2` to the URL once to bust the cache |
| `git push failed ... The workflow needs 'permissions: contents: write'` | Workflow token is read-only | Add `permissions: contents: write` to the workflow; keep `actions/checkout` credentials (`persist-credentials` default) |
| `The working directory is not a git repository; run actions/checkout first` | `publish-branch` used without a checkout step | Add `actions/checkout` before Commit Rider |
| `Could not push ... kept changing` | Another job kept pushing to the publish branch | Avoid running two workflows against the same branch at once |
| Scheduled workflow does not run | Not on the default branch; or disabled after ~60 days of repository inactivity | Run it manually once and re-enable it in the Actions tab |
| Action fails on a Windows runner | The Action's script targets `bash` with a POSIX virtual-environment layout | Use `ubuntu-latest` (or macOS) |
| `Pillow` fails to install | Very new/old Python without a wheel | Keep the default `python-version: "3.12"` |
| Overlay text is a plain font | DejaVu Sans is not installed (it is on GitHub's Ubuntu runners) | Install `fonts-dejavu-core`; the built-in fallback font works but is plainer |

Still stuck? Open an issue with the *Bug report* template and include your settings (never a token) and the
log from a `-vv` run.
