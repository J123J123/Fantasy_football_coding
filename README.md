# Fantasy football reports and data

Collect Yahoo league archives, generate weekly HTML reports, and publish compressed
silver player/schedule tables with a searchable download page.

## Local CLI

Run from the repository root (Python 3.11 or newer):

```bash
python -m pip install './yahoo-fantasy-data[dev]' -r report_code/requirements.txt
python -m report_code.publish --backfill
```

The default run file is `report_runs.json`, a JSON list of dictionaries:

```json
[
  {"league_id": "134317", "year": 2025, "nickname": "CFFL_A"},
  {"league_id": "889216", "year": 2025, "nickname": "Ferda"}
]
```

Each entry selects a Yahoo league ID, season year, and local folder nickname.
Entries can use different years. The included file selects all four 2025 leagues.
Use another file with `python -m report_code.publish --config my_runs.json --backfill`.
Paths are relative to the working directory; run from the repository root.
`league_history.json` remains a reference of historical IDs, but does not control
publishing runs.

Week is optional:

- With `--backfill`, query Yahoo league metadata. For an active season, collect
  through `current_week - 1`, capped at the league's `end_week`. For a finished
  season (`is_finished`), collect through `end_week`. This deliberately waits for
  Yahoo's week rollover rather than including an in-progress week.
- Without `--backfill`, use each local archive's `last_collected_week`; no Yahoo
  requests are made. This is the last archived week, not a guarantee of complete
  or reconciled source data.
- Before a season has completed a week, skip that run. Missing week metadata
  produces an error rather than guessing from the calendar.
- Add `"week": 10` to an individual entry to pin a report period, or use
  `--week 10` to override all selected runs.

Optional entry fields are `enabled` (default `true`), `overwrite` (default
`false`), `strict` (default `false`), and `template` (`original`, `pc`, or `both`, default
`original`). For example:

```json
[
  {"league_id": "134317", "year": 2025, "nickname": "CFFL_A", "template": "both", "strict": true},
  {"league_id": "801641", "year": 2024, "nickname": "CFFL_A", "week": 10, "enabled": false}
]
```

The pipeline backfills from week 1 through the resolved week, writes the selected HTML
report versions to `docs/NICKNAME_YEAR.html` and/or `docs/NICKNAME_YEAR_pc.html`, exports `silver_player.csv.gz` and
`silver_schedule.csv.gz` to `docs/data/NICKNAME/YEAR/`.
The permanent `docs/index.html` fetches the public GitHub file list in JavaScript;
no index generation or file manifest is needed. Each run overwrites these stable paths with the latest output for that league/season.
No folder cleanup is needed. If you stop generating a report version, delete its
HTML file manually. Source archives are retained. Player exports
include archived weeks through the report week; schedule exports may include
future matchups from that snapshot.

- Use `--leagues CFFL_A Ferda` to filter enabled runs by nickname across years.
- Omit `--backfill` to build entirely from local archives.
- Use `--overwrite` with `--backfill` to refresh existing snapshots for every run.
- Use `--template pc` for only PC reports, or `--template both` for original and PC
  HTML reports for every run. Omit the flag to honor each entry's `template`;
  omitted entry templates default to `original`. Data is exported once either way.
- Add `--strict` to require official score reconciliation for every run.
  Otherwise each entry controls strict checking; reports retain data-quality
  annotations and missing values by default.

The pipeline stops on collector failures; successful partial archives can be
reused on the next run. It does not commit or push when run locally.
The underlying CLIs remain available: `python -m yahoo_fantasy_data --help` and
`python -m report_code --help`. See [report documentation](report_code/README.md)
and [collector documentation](yahoo-fantasy-data/README.md).

## GitHub Action

Commit and push the local code first: Actions checks out GitHub's `main` branch,
not uncommitted files on your computer. In **Actions → Backfill and publish league
reports → Run workflow**, select `main` and the JSON configuration path
(default `report_runs.json`). League IDs, years, nicknames, and optional settings
come from that file; no season or week input is required in the Action.

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
4. Update `report_runs.json` with the league IDs and years you want to run.
   The included run file currently selects 2025.

The workflow deploys Pages explicitly because [pushes made using `GITHUB_TOKEN`
do not trigger a branch-based Pages build](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
The index uses the [GitHub Trees API](https://docs.github.com/en/rest/git/trees)
to list HTML and CSV/CSV.gz files under `docs` on `main` in
`J123J123/Fantasy_football_coding`. Search and download links are built in the
browser. Push new files and deploy Pages to make them available; use **Refresh
files** to reload the listing. The public API needs no token; network errors or
API limits show a retry message and a link to browse GitHub.

The index also opens with a local HTTP server
(`python -m http.server --directory docs`), but its listing still comes from
GitHub, so unpushed files are not listed. Open local HTML reports directly to
preview them. When forking the repository, update `repository` and `branch` in
`docs/index.html` and the GitHub browse links. Its CSV link
uses browser gzip decompression; the compressed file remains directly downloadable
if the browser does not support decompression. Browser decompression requires HTTP
hosting, rather than opening the page with a `file://` URL.

## Tests

```bash
python -m pytest report_code/tests yahoo-fantasy-data/tests -m 'not integration' -q
```
