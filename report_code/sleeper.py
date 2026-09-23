"""Sleeper's public API translated into the shared report archive schema.

Documented league endpoints: https://docs.sleeper.com/ . The stats and
projections endpoints are public but undocumented; retain missing data as null.
"""
from collections import Counter, defaultdict
from functools import cached_property
import json
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from yahoo_fantasy_data.config import storage_league_name

SLOTS = {'FLEX': 'W/R/T', 'SUPER_FLEX': 'Q/W/R/T', 'REC_FLEX': 'W/T',
         'WRRB_FLEX': 'W/R', 'DEF': 'DEF', 'IDP_FLEX': 'IDP_FLEX'}
NOTES = [
    'Sleeper projections are reconstructed with league scoring from its public, undocumented stats service; historical projections may have been revised.',
    'Historical Sleeper IR players are treated as eligible bench players for lineup analysis. Taxi-slot eligibility remains unavailable.',
    'Player names, positions, team names, divisions and league settings reflect collection time; weekly ownership and starters come from historical matchups.',
]


class SleeperClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])))
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            response = self.session.get('https://api.sleeper.app/' + path, timeout=45)
            response.raise_for_status()
            self.cache[path] = response.json()
            time.sleep(0.1)
        return self.cache[path]

    @cached_property
    def players(self):
        return self.get('v1/players/nfl')


def league_metadata(year, league_id, client=None):
    client = client or SleeperClient()
    league = client.get(f'v1/league/{league_id}')
    if not league or league.get('sport') != 'nfl':
        raise ValueError('Sleeper league was not found or is not an NFL league')
    if str(league['season']) != str(year):
        raise ValueError(f"Sleeper league {league_id} belongs to {league['season']}, not {year}")
    settings = league['settings']
    if settings.get('best_ball') or settings.get('league_average_match'):
        raise ValueError('Sleeper best-ball and league-median extra games are not supported')
    if int(settings.get('start_week', 1)) != 1:
        raise ValueError('Sleeper leagues starting after week 1 are not supported')
    state = client.get('v1/state/nfl')
    finished = league['status'] == 'complete' or int(state['season']) > year
    if finished:
        current = 18
    elif int(state['season']) < year or state['season_type'] == 'pre':
        current = 1
    elif state['season_type'] == 'post':
        current, finished = 18, True
    else:
        current = int(state['week'])
    # A scored leg can lag the NFL rollover; do not collect unfinished results.
    if not finished and settings.get('last_scored_leg') is not None:
        current = min(current, int(settings['last_scored_leg']) + 1)
    playoff_start = int(settings.get('playoff_week_start', 0))
    return dict(provider='sleeper', league_id=str(league_id),
                league_key=f'sleeper.l.{league_id}', league_name=league['name'],
                season=year, current_week=current, is_finished=finished,
                start_week=1, end_week=18, uses_playoff=int(playoff_start > 0),
                playoff_start_week=playoff_start or None, notes=NOTES), league


def weekly_stats(client, kind, year, week):
    rows = client.get(f'{kind}/nfl/{year}/{week}?season_type=regular')
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'Sleeper {kind}: no weekly data for {year} week {week}')
    result = {}
    for row in rows:
        if str(row.get('season')) != str(year) or row.get('week') != week or row.get('season_type') != 'regular':
            raise ValueError(f'Sleeper {kind}: incorrect weekly coverage')
        pid = str(row['player_id'])
        if pid in result:
            raise ValueError(f'Sleeper {kind}: duplicate player {pid}')
        result[pid] = row
    return result


def score(row, scoring):
    if row is None or not isinstance(row.get('stats'), dict) or not row['stats']:
        return None
    return round(sum(float(row['stats'].get(stat, 0) or 0) * weight
                     for stat, weight in scoring.items()), 2)


def backfill_season(season, league_id, start_week, end_week, overwrite=False, *,
                    settings, league_nickname, refresh_latest=True, client=None):
    year = season
    client = client or SleeperClient()
    metadata, league = league_metadata(year, league_id, client)
    completed = metadata['current_week'] if metadata['is_finished'] else metadata['current_week'] - 1
    regular_end = (metadata['playoff_start_week'] or 19) - 1
    if not 1 <= start_week <= end_week <= min(completed, regular_end):
        raise ValueError('Sleeper collection requires completed regular-season weeks')
    root = settings.data_dir / storage_league_name(league_nickname, league_id) / str(year)
    old = {}
    if (root / 'metadata.json').exists():
        old = json.loads((root / 'metadata.json').read_text())
        if old.get('provider') != 'sleeper' or str(old.get('league_id')) != str(league_id):
            raise ValueError('Archive destination already belongs to a different league/provider')
    rosters = client.get(f'v1/league/{league_id}/rosters')
    users = {u['user_id']: u for u in client.get(f'v1/league/{league_id}/users')}
    names = {}
    for roster in rosters:
        user = users.get(roster.get('owner_id'), {})
        names[roster['roster_id']] = ((user.get('metadata') or {}).get('team_name')
                                    or user.get('display_name') or f"Team {roster['roster_id']}")
    slots = [SLOTS.get(p, p) for p in league['roster_positions'] if p != 'BN']
    matchups = {w: client.get(f'v1/league/{league_id}/matchups/{w}')
                for w in range(1, regular_end + 1)}
    key = lambda team: f"{metadata['league_key']}.t.{team}"
    schedule = {t: {'team_key': key(t)} for t in names}
    for week, matches in matchups.items():
        pairs = defaultdict(list)
        for match in matches:
            if match.get('matchup_id') is not None:
                pairs[match['matchup_id']].append(match['roster_id'])
        for pair in pairs.values():
            if len(pair) != 2:
                raise ValueError(f'Sleeper week {week}: expected head-to-head matchups')
            a, b = pair
            schedule[a][f'week_{week}'] = key(b)
            schedule[b][f'week_{week}'] = key(a)
        for row in schedule.values():
            row.setdefault(f'week_{week}', None)
    picks = {}
    for draft in reversed(client.get(f'v1/league/{league_id}/drafts')):
        if str(draft['season']) == str(year) and draft['status'] == 'complete':
            for pick in client.get(f"v1/draft/{draft['draft_id']}/picks"):
                picks[str(pick['player_id'])] = dict(player_id=str(pick['player_id']),
                    round=pick['round'], pick=pick['pick_no'], team_id=pick['roster_id'])
    statuses = {}
    for week in range(start_week, end_week + 1):
        folders = ['draft', 'league_settings', 'player_data', 'projection_data',
                   'schedule', 'team_data', 'divisions', 'points recon']
        paths = {f: root / f / f"{f.replace(' ', '_')}_week_{week}.csv.gz" for f in folders}
        if not overwrite and not (refresh_latest and week == end_week) and all(p.exists() for p in paths.values()):
            statuses[week] = {f: 'skipped' for f in folders}
            continue
        matches = matchups[week]
        if {m['roster_id'] for m in matches} != set(names):
            raise ValueError(f'Sleeper week {week}: incomplete historical matchups')
        stats = weekly_stats(client, 'stats', year, week)
        projections = weekly_stats(client, 'projections', year, week)
        base = dict(season=year, league_id=str(league_id), league_key=metadata['league_key'], week=week)
        team_rows, official, actual = [], [], {}
        for match in matches:
            team = match['roster_id']
            starters = match.get('starters') or []
            if len(starters) != len(slots):
                raise ValueError(f'Sleeper week {week}, team {team}: unexpected starter slots')
            players = set(map(str, match.get('players') or [])) | (set(map(str, starters)) - {'0'})
            assignments = {str(pid): slot for pid, slot in zip(starters, slots) if str(pid) != '0'}
            # Historical matchups include IR players without identifying them.
            # Treat them as bench candidates by the report's Sleeper convention.
            # Current roster limits need not match historical roster sizes.
            known = not league['settings'].get('taxi_slots')
            for pid in sorted(players):
                if pid in actual:
                    raise ValueError(f'Sleeper week {week}: duplicate roster ownership for {pid}')
                actual[pid] = (match.get('players_points') or {}).get(pid)
                team_rows.append(dict(player_id=pid, team_id=team, team_name=names[team],
                    roster_slot=assignments.get(pid, 'BN'), is_starting=pid in assignments,
                    roster_eligibility_known=known))
            # Empty starter slots score zero, and remain visible in reconciliation.
            for index, pid in enumerate(starters):
                if str(pid) == '0':
                    empty = f'empty-{team}-{index}'
                    actual[empty] = 0.0
                    team_rows.append(dict(player_id=empty, team_id=team, team_name=names[team],
                        roster_slot=slots[index], is_starting=True, roster_eligibility_known=False))
            official.append(dict(team_id=team, official_points=match['custom_points']
                                if match.get('custom_points') is not None else match.get('points')))
        player_rows, projection_rows = [], []
        for pid in sorted(set(stats) | set(actual)):
            player = client.players.get(pid, {})
            historical = stats.get(pid, {}).get('player') or {}
            pos = historical.get('position') or player.get('position')
            if pid not in actual and pos not in {'QB', 'RB', 'WR', 'TE', 'K', 'DEF', 'DL', 'LB', 'DB'}:
                continue
            player_rows.append(dict(player_id=pid,
                player_name=player.get('full_name') or ' '.join(filter(None, [player.get('first_name'), player.get('last_name')])) or pid,
                position=pos, eligible_positions=','.join(historical.get('fantasy_positions') or player.get('fantasy_positions') or [pos or '']),
                nfl_team=stats.get(pid, {}).get('team') or player.get('team'),
                fantasy_points_actual=actual[pid] if pid in actual else score(stats.get(pid), league['scoring_settings'])))
            projection_rows.append(dict(player_id=pid, projected_points=score(projections.get(pid), league['scoring_settings']), projection_week_returned=week))
        config = [dict(setting_type='league', num_playoff_teams=league['settings'].get('playoff_teams'),
                       playoff_start_week=metadata['playoff_start_week'], uses_playoff=metadata['uses_playoff'])]
        config += [dict(setting_type='roster_position', position=p, count=n) for p, n in Counter(slots).items()]
        config += [dict(setting_type='scoring_stat', stat_id=s, value=v) for s, v in league['scoring_settings'].items()]
        divisions = [dict(team_id=r['roster_id'], team_name=names[r['roster_id']],
            division_id=r['settings'].get('division'), division_name=(league.get('metadata') or {}).get(f"division_{r['settings'].get('division')}")) for r in rosters]
        tables = {'draft': pd.DataFrame(list(picks.values()), columns=['player_id', 'round', 'pick', 'team_id']),
                  'league_settings': pd.DataFrame(config), 'player_data': pd.DataFrame(player_rows),
                  'projection_data': pd.DataFrame(projection_rows), 'team_data': pd.DataFrame(team_rows),
                  'points recon': pd.DataFrame(official), 'divisions': pd.DataFrame(divisions),
                  'schedule': pd.DataFrame(schedule.values())}
        for folder, table in tables.items():
            for column, value in base.items():
                table[column] = value
            path = paths[folder]
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            table.to_csv(temporary, index=False, compression={'method': 'gzip', 'mtime': 0})
            temporary.replace(path)
        statuses[week] = {f: 'written' for f in folders}
    root.mkdir(parents=True, exist_ok=True)
    metadata['last_collected_week'] = max(end_week, old.get('last_collected_week', 0))
    (root / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return statuses
