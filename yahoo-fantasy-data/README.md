# yahoo-fantasy-data

`yahoo-fantasy-data` archives **public** Yahoo Fantasy Football leagues into immutable, compressed CSV snapshots. It is intended to be a small, reusable data repository suitable for a public GitHub project. It never writes credentials, browser cookies, or private-league data.

Yahoo has two relevant interfaces: the supported Fantasy Sports API, which commonly requires OAuth, and an unofficial read-only public endpoint. This project attempts the anonymous public endpoint first. OAuth is optional and is never needed just to install, run unit tests, or make anonymous attempts. Unofficial endpoints can change or stop providing historical data at any time.

## Install

```bash
cd yahoo-fantasy-data
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Optional OAuth configuration belongs in a local `.env` (copy `.env.example`) or environment variables:

```text
YAHOO_CLIENT_ID=
YAHOO_CLIENT_SECRET=
YAHOO_REFRESH_TOKEN=
YAHOO_GAME_ID=
```

No value is included in the repository. `YAHOO_GAME_ID` is only an explicit fallback if Yahoo cannot discover a season's NFL game ID.

## Collect data

```bash
python -m yahoo_fantasy_data collect --season 2025 --league 707737 --week 5
python -m yahoo_fantasy_data backfill --season 2025 --league 707737
python -m yahoo_fantasy_data test --season 2025 --league 707737 --week 5
```

`collect` writes each independent collector that succeeds. A failed projection request, for example, does not discard successfully retrieved roster or schedule snapshots. Existing snapshots are skipped by default; use `--overwrite` only when deliberately replacing a file. `backfill` resolves `end_week` from league metadata when available and proceeds sequentially with a small configurable delay.

The `test` command performs no writes. It reports anonymous/public reachability, OAuth requirements, row counts, and small player-projection and roster samples.

## Output layout

```text
data/{league_id}/{season}/
  player_data/player_data_week_{week}.csv.gz
  projection_data/projection_data_week_{week}.csv.gz
  team_data/team_data_week_{week}.csv.gz
  schedule/schedule_week_{week}.csv.gz
  draft/draft_week_{week}.csv.gz
  league_settings/league_settings_week_{week}.csv.gz
  metadata.json
```

Week numbers are intentionally not zero-padded. Every practical dataset carries `season`, `week`, `game_id`, `league_id`, and `league_key` (for example `461.l.707737`). Metadata records collection time, league identifiers, discovered week bounds, and the status/source of each collector.

## Dataset meanings

- `player_data` is the available league player universe, including ownership and actual information Yahoo returns.
- `projection_data` is Yahoo's individual-player projection response for the requested week. It makes an anonymous request with historical-week and projected-stat parameters; it never scrapes HTML or uses cookies. If Yahoo demands authentication, it reports an authentication/projection-unavailable result instead of creating a fake file.
- `team_data` is a historical roster snapshot: one player in one fantasy-team slot. It requests the historical week directly and raises a clear error rather than substituting a current roster.
- `schedule` contains fantasy-team matchup data only, not roster assignments.
- `draft` preserves draft results in a weekly snapshot for a uniform filesystem contract.
- `league_settings` provides readable league, roster-position, and scoring-stat rows rather than one opaque JSON blob.

Yahoo response fields vary by endpoint and season. The normalizers retain extra fields where possible, use snake_case headers, and do not manufacture unavailable fields. Historical projection and roster availability must be validated for each league/season. Compare `team_data` between two weeks to inspect real roster changes; the package does not infer transactions.

## Read compressed files

```python
import pandas as pd

projections = pd.read_csv(
    "data/707737/2025/projection_data/projection_data_week_5.csv.gz"
)
rosters = pd.read_csv(
    "data/707737/2025/team_data/team_data_week_5.csv.gz"
)
```

## Tests

Unit tests mock all Yahoo traffic:

```bash
pytest
```

The optional manual anonymous smoke test for the known public 2025 league is deliberately opt-in:

```bash
YAHOO_INTEGRATION=1 pytest -m integration tests/test_integration_public.py
```

It uses no OAuth or cookies. Run the CLI `test` command first and treat its report as the authoritative statement of which endpoints Yahoo currently permits anonymously.
