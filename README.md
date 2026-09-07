# Fantasy football reports and data

Collect Yahoo league archives, generate weekly HTML reports, and publish compressed
silver player/schedule tables with a searchable download page.

## Local CLI

Run from the repository root (Python 3.11 or newer):

```bash
python -m pip install './yahoo-fantasy-data[dev]' -r report_code/requirements.txt
python -m report_code.publish --season 2025 --week 17 --backfill
```

This backfills weeks 1–17 for every league with a 2025 entry in
`yahoo-fantasy-data/league_history.json`, writes one report per league to `docs/`,
exports `silver_player.csv.gz` and `silver_schedule.csv.gz` to
`docs/data/LEAGUE/SEASON/week17/`, and rebuilds `docs/index.html` with links to
all existing reports and downloads. Player exports include weeks through the
selected week; schedule exports can include future matchups from that snapshot.
Existing reports and downloads remain in the index.

- Use `--leagues CFFL_A Ferda` to select leagues.
- Omit `--backfill` to build entirely from local archives without Yahoo requests.
- Use `--overwrite` with `--backfill` to refresh already collected snapshots.
- Set `--week` to the last completed week, not an upcoming or in-progress week.
- Use `--template pc` for work-appropriate report wording.
- Add `--strict` to require all team-week scores to reconcile with official scores.
  By default reports retain their data-quality annotations and missing values.

The pipeline stops on collector failures; successful partial archives can be
reused on the next run. It does not commit or push when run locally.
The underlying CLIs remain available: `python -m yahoo_fantasy_data --help` and
`python -m report_code --help`. See [report documentation](report_code/README.md)
and [collector documentation](yahoo-fantasy-data/README.md).

## GitHub Action

Commit and push the local code first: Actions checks out GitHub's `main` branch,
not uncommitted files on your computer. In **Actions → Backfill and publish league
reports → Run workflow**, select `main`, season, last completed week, optional
league nicknames, overwrite behavior, and report template.
Enable the strict input if score reconciliation must pass before publishing.

The workflow installs the checked-out collector, runs tests, backfills leagues,
builds reports and silver downloads, commits `docs/` and the source archives to
`main`, and deploys `docs/` to GitHub Pages. It is manually triggered; no automatic
schedule is assumed. Concurrent publishing runs are serialized. A conflicting
remote push or branch protection causes a normal push failure; no force push is used.

Repository setup:

1. Set **Settings → Pages → Build and deployment → Source** to **GitHub Actions**.
2. Permit the workflow to write repository contents; branch rules must permit its
   bot to push to `main`.
3. If Yahoo authentication is needed, configure Actions secrets
   `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, and `YAHOO_REFRESH_TOKEN` using the
   collector's authorization instructions. Public access is attempted first.
4. Add season-specific league IDs to `league_history.json` before running a new
   season. The included mapping currently ends at 2025.

The workflow deploys Pages explicitly because [pushes made using `GITHUB_TOKEN`
do not trigger a branch-based Pages build](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
The index is plain HTML and also works
with a local HTTP server (`python -m http.server --directory docs`). Its CSV link
uses browser gzip decompression; the compressed file remains directly downloadable
if the browser does not support decompression. Browser decompression requires HTTP
hosting, rather than opening the page with a `file://` URL.

## Tests

```bash
python -m pytest report_code/tests yahoo-fantasy-data/tests -m 'not integration' -q
```
