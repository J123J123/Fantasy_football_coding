# Report processing

`ReportProcessor` owns the bronze, silver, and gold pandas tables for one league
and season. Report calculations live in one Python module per HTML section.
Tables are lazy and cached; create a new processor after changing input files.

From the repository root:

```bash
.venv/bin/python -m pip install -r report_code/requirements.txt
.venv/bin/python -m report_code yahoo-fantasy-data/data/Ferda/2025 \
  --week 5 --json report_code/output/week5.json --html report_code/output/week5.html
```

Create the output directory first. Omit `--week` to use metadata `current_week`,
falling back to `last_collected_week`. This is the archive's week, not today's
NFL week. Input may be the league/season directory or its `metadata.json`.

```python
from report_code import ReportProcessor

report = ReportProcessor("yahoo-fantasy-data/data/Ferda/2025", current_week=5)
players = report.bronze_player
joined = report.silver_player
checks = report.silver_reconciliation
season_checks = report.silver_season_reconciliation
expertise = report.gold_managerial_expertise
payload = report.to_dict()              # Dict matching the existing HTML renderer
json_text = report.to_json()            # Optional output path also accepted
report.write_html("report_code/output/week5.html")
```

`silver_player` exposes 19 core report fields: `player_id`, `player_name`, `week`,
`position`, `eligible_positions` (a sorted list), `nfl_team`, `bye_week`,
`team_id`, `team_name`, `roster_slot`, `is_starting`, `actual_points`,
`projected_points`, `draft_round`, `draft_pick`, `draft_team_id`, `is_stud`,
`is_dud`, and `volatility_known`. Team fields describe weekly roster ownership;
`draft_team_id` identifies the original drafting team. Raw Yahoo stats, metadata,
and duplicate source fields remain available in the bronze tables.

It also includes `rank_<slot>` for each distinct starting position in the league
(for example, `rank_qb`, `rank_rb`, and `rank_w_r_t` for W/R/T flex), plus
`is_optimal`. Ranks use actual points, highest first, within each week and fantasy
team; unrostered players form a separate FA pool. Ties share the minimum rank
(1, 1, 3). Each position ranks its entire eligible pool independently, including
flex; repeated slots such as RB1/RB2 share one rank column. Bench players are
included, reserves (IR/NA/etc.) are excluded. Ineligible or unscored players have
null ranks; known scores are ranked even when another player's score is missing.

`is_optimal` selects one highest-scoring legal lineup per team/week and FA/week,
respecting repeated positions, flex, and multi-position eligibility without
reusing players. Equally good lineups may have different members; the flag marks
one solution. It is null for playable players when missing scores, missing
archived roster players, or insufficient eligible players prevent optimization.
Reserves are always false. Team flags agree with `silver_lineups` selections.

## Tables and loading

- Bronze properties: `bronze_draft`, `bronze_settings`, `bronze_player`,
  `bronze_projection`, `bronze_schedule`, `bronze_team_data`, `bronze_divisions`,
  `bronze_points_recon`.
- `read_files(table, latest=False)` reads CSV or compressed CSV files. Player,
  projection, and roster snapshots concatenate from season start through the
  selected week. Draft, settings, and schedule choose the newest available
  snapshot at or before that week. Future snapshots are never substituted.
  Duplicate snapshots/keys raise errors rather than multiplying player rows.
- Override inputs with `data_files={"player": ["/path/player_week_1.csv.gz",
  "/path/player_week_2.csv.gz"], "draft": "/path/draft_week_2.csv.gz"}`.
  Keys match the bronze property suffixes. A directory is also accepted.
- `silver_player` is a left join from player data. Projection and roster join
  on `(player_id, week)`; draft joins only on `player_id`. Every source column
  is retained with `projection_`, `team_`, or `draft_` prefixes. Canonical
  `team_id` and `roster_slot` come from that week's roster. Unrostered players
  remain in the universe for free-agent/baseline calculations.
- Other silver properties: `silver_schedule`, `silver_team_week`,
  `silver_lineups`, `silver_reconciliation`, `silver_season_reconciliation`.
- Gold properties: `gold_boned_index`, `gold_boned_detail`,
  `gold_freaky_friday`, `gold_bhole`, `gold_studs_duds`, `gold_grower_shower`,
  `gold_managerial_expertise`, `gold_vobl`, `gold_playoff_odds`,
  `gold_draft_analysis`. Each returns a DataFrame; `gold_tables` returns all ten.
  Matrix/map report cells remain dictionaries inside DataFrames. Each module's
  `payload()` converts its gold table into the template's nested structure.

## Reconciliation and missing data

Reconciliation covers **every team and week through the requested week**, even
when a weekly file is absent. Starter points are summed, excluding the bench
and reserve slots. Missing player scores and roster players absent from the
player universe invalidate the sum. Season-coverage player totals are never
used as weekly scores. Projections returned for another week are invalidated.

`bronze_points_recon` reads weekly snapshots from the archive's `points recon/`
folder through the selected week. `silver_reconciliation` automatically joins
their independent Yahoo `official_points` on `(team_id, week)` and compares them
with the starter totals. Missing snapshots leave those weeks unverified;
duplicate team/week keys raise an error. You can override the archived source
with `data_files={"points_recon": ...}` or supply an independent CSV with
`official_scores_path` (which takes precedence):

```csv
team_id,week,official_points
1,1,103.42
2,1,112.80
```

```python
report = ReportProcessor(
    "yahoo-fantasy-data/data/Ferda/2025", 5,
    official_scores_path="official_scores.csv", tolerance=0.01,
)
report.validate_reconciliation()  # Raises unless every team-week matches
```

CLI equivalents: `--official-scores official_scores.csv --strict`.
Without official scores, a complete calculated total is **unverified**, never
"matched". Other statuses are `missing_player_points_or_roster` and `mismatch`.
Season totals require complete weekly totals; differences cannot cancel out
and hide weekly mismatches. JSON includes both checks in `data_quality`.

**Archive limitation:** Ferda 2025 week 5 has 1,250 blank actual player scores
and season-coverage statistics. This pipeline cannot recover weekly points
from those files. Collect corrected weekly player scores and independent team
scores to obtain meaningful, reconciled scoring reports. Missing values become
JSON `null` and display as em dashes. No synthetic scores are inserted.

## Calculation conventions

The sample PDF supplies the section definitions and the XLSB supplies the
legacy table structure and cached examples. The workbook and PDF describe
different report periods, so these are not a numerical parity fixture. Excel
formula bytecode/VBA is not ported; the explicit conventions below define the
Python implementation where the sample does not fully specify a formula.

- Boned Index: `(mean opponent score / mean opponent average against everyone
  else - 1) * 100`, recalculated through each week. Repeated matchups against
  the same focal team are excluded from the opponent baseline. Week 1 has no
  index; undefined/zero-denominator averages stay null.
- Freaky Friday: swap the schedules, replacing a self-opponent with the schedule
  owner's score. Head-to-head compares each team's score in the same week.
- BHOLE: wins at offsets -10, -5, -2.5, 0, 2.5, 5, 10; range is the difference
  between extreme offsets. Width is mean absolute matchup margin.
- Stud: actual > twice projected, actual >= 20. Dud: actual <= 25% of projected,
  projected >= 10. Starter counts and opponent counts feed the volatility report.
- Grower/Shower: weekly normal probability uses observed matchup margin divided
  by combined historical sample standard deviations. Expected wins blend with
  actual-vs-opponent-average, average-vs-opponent-actual, and average-vs-average
  using weights 0.8, 0.075, 0.075, 0.05. Ratio is actual wins / blend.
  This is an explicit approximation, not verified Excel formula parity.
- Lineups: exact bipartite assignment maximizes actual or projected points with
  positional eligibility and flex constraints. Players cannot occupy two slots.
  Bench players are eligible; IR/IR+/NA/RES players are excluded. Missing scores
  among eligible candidates leave optimization unavailable. Equally good
  projection lineups count as following Yahoo, even if player identities differ.
- VOBL: league size N sets the baseline rank. Allocate the top N candidates per
  slot, taking the Nth score as the baseline, then remove those candidates before
  the next slot. Thus RB2 uses rank 2N; flex follows positional slots. Repeated
  actual slots are ordered by points. This generalizes the PDF's 12-team rule.
- Bench Mob: the highest-scoring legal lineup from that week's unrostered pool.
  VOBM is points above it; WOBM/WOBL count wins against the weekly comparison.
- Draft buckets: 1–5, 6–10, 11–16, FA; the third becomes 11+ for longer drafts. Players
  drafted by a different manager count as FA, including traded players.
- Ties count as half a win throughout. Zero denominators remain null.
- Manager names are not in the collector's roster schema, so team names serve
  as display names. You can replace `report.teams["manager"]` before export.

## Playoff simulation

`ReportProcessor(data_path, current_week)` reads the playoff qualifier count and
start week from league settings. Byes are derived from the standard bracket
lookup in `playoff_odds.PLAYOFF_ROUNDS` (1–16 qualifiers), using
`2 ** rounds - qualifiers`: 4 teams / 2 rounds gives 0 byes, 6 teams / 3 rounds
gives 2, 8 teams / 3 rounds gives 0, and 12 teams / 4 rounds gives 4.
Rounds assume one matchup per week. The archived bye field is not required.
Optional `playoff_byes` and `playoff_teams` constructor arguments (or equivalent
CLI flags) override these defaults; an explicit zero bye count is respected.
Counts outside the lookup require a `playoff_byes` override.
`simulation_count`
defaults to 10,000 (1,000 seasons for each of ten standard-deviation exponents)
and `random_seed` to 42. A custom `simulation_count` must be a positive multiple
of 10 so each exponent receives equal weight.

For scoring distributions, the team weight is
`min(current_week, playoff_blend_weeks) / playoff_blend_weeks`. The optional
constructor argument `playoff_blend_weeks` defaults to 10; override it to change how long
league-wide information contributes. Historical odds use the same configured window.
Both the mean and sample standard deviation are weighted averages of the
manager's statistic and the league-wide statistic, with the remaining weight
on the league. League statistics pool all completed regular-season team-week
scores through the report week; the league standard deviation is calculated
over those individual scores, not over team averages. Both standard deviations
use `ddof=1`. Week 2 uses 20% team and 80% league information;
week 10 onward uses only team statistics with the default window. These parameters stay fixed while
simulating future weeks, and each historical outlook uses its own report week.

After blending, each simulation group uses `blended_std ** exponent`, with
exponents 0.25, 0.50, …, 2.50. Each simulated season retains its group's exponent
for every team and remaining week. All groups contribute equally to the final
odds. Draws use the blended mean and transformed standard deviation, then clamp
to `[60, 200]` (values outside the range become the nearest endpoint, rather
than being redrawn). Existing actual scores are not capped. Clipping can create
exact ties at the endpoints; these still count as half a win.


The HTML section also includes an odds-by-week line chart with a dropdown for
Playoffs, Division, Wildcard, Bye, and Last. `playoff_odds.history` in the JSON
contains each week's independently calculated outlook using only snapshots
available through that week. Missing snapshots or insufficient scoring history
produce gaps with explanations. History is cached on the processor; the first
export takes longer because it calculates every week through `current_week`.

Standings use wins, then season points, then a seeded random tie-break.
For divisions, pass `divisions={"1": "East", "2": "West", ...}` covering every
team, or `--divisions divisions.json`. Each division winner qualifies and
receives a top seed; the remaining qualifiers are wildcards. Byes go to the
first seeds. Last-place probability always uses overall regular-season
standings. Without a mapping, qualification uses a single table (`division`
is zero, `wildcard` equals overall qualification). These seeding conventions
must match your league; division mappings are not present in the archives.
The model requires two complete scored games per team and a reciprocal,
complete remaining regular-season schedule. Archived schedules stop at the
regular season; postseason matchup-dependent metrics remain unavailable when
those matchups are absent.

## Verification

```bash
.venv/bin/python -m pytest report_code/tests -q
```

Synthetic archives test known totals, missing scores/weeks, duplicate joins,
projection weeks, official mismatches, flex optimization, draft ownership,
reproducible simulation, null handling, and safe embedded HTML JSON.
