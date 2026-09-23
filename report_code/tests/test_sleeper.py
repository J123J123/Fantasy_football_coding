import json

import pytest

from report_code import ReportProcessor, publish, sleeper
from yahoo_fantasy_data.config import Settings


class Client:
    players = {str(i): {'full_name': f'Player {i}', 'position': 'QB', 'fantasy_positions': ['QB']} for i in range(1, 6)}

    def __init__(self):
        self.league = dict(name='Test', sport='nfl', season='2026', status='in_season',
            settings=dict(playoff_week_start=3, playoff_teams=2, last_scored_leg=2),
            roster_positions=['QB', 'BN'], scoring_settings={'pass_yd': .04, 'pass_td': 4})

    def get(self, path):
        if path == 'v1/league/123':
            return self.league
        if path == 'v1/state/nfl':
            return dict(season='2026', week=3, season_type='regular')
        if path.endswith('/rosters'):
            return [dict(roster_id=i, owner_id=str(i), settings={'division': i}) for i in (1, 2)]
        if path.endswith('/users'):
            return [dict(user_id=str(i), display_name=f'Manager {i}') for i in (1, 2)]
        if path.endswith('/drafts'):
            return [dict(season='2026', status='complete', draft_id='456')]
        if path.endswith('/picks'):
            return [dict(player_id=str(i), round=1, pick_no=i, roster_id=i) for i in (1, 2)]
        if '/matchups/' in path:
            # Current rosters are deliberately unused; ownership comes from this week.
            return [dict(roster_id=1, matchup_id=1, players=['1', '3'], starters=['1'],
                         players_points={'1': 20, '3': 25}, points=20, custom_points=None),
                    dict(roster_id=2, matchup_id=1, players=['2', '4'], starters=['2'],
                         players_points={'2': 10, '4': 8}, points=10, custom_points=None)]
        if path.startswith(('stats/', 'projections/')):
            week = int(path.split('/')[3].split('?')[0])
            return [dict(player_id=str(i), season='2026', week=week, season_type='regular',
                         player=self.players[str(i)], stats={'pass_yd': i * 100, 'pass_td': 1}) for i in range(1, 6)]
        raise AssertionError(path)


def collect(tmp_path, client=None):
    sleeper.backfill_season(2026, '123', 1, 2, settings=Settings(data_dir=tmp_path),
                            league_nickname='Test', client=client or Client())
    return tmp_path / 'Test' / '2026'


def test_end_to_end_archive_and_report(tmp_path):
    root = collect(tmp_path)
    report = ReportProcessor(root, 2, simulation_count=10)
    report.validate_reconciliation()
    assert report.silver_reconciliation.status.eq('matched').all()
    assert report.silver_schedule.opponent_id.tolist() == ['2', '1', '2', '1']
    assert report.divisions == {'1': '1', '2': '2'}
    players = report.silver_player
    assert players.query("player_id == '1'").actual_points.tolist() == [20, 20]
    assert players.query("player_id == '5'").actual_points.tolist() == [24, 24]
    assert players.query("player_id == '1'").projected_points.tolist() == [8, 8]
    assert players.query("player_id == '1'").draft_team_id.astype(str).tolist() == ['1', '1']
    assert report.silver_lineups.optimal_points.tolist() == [25, 25, 10, 10]
    assert report.gold_playoff_odds.make_playoffs.notna().all()
    report.write_html(tmp_path / 'report.html')
    html = (tmp_path / 'report.html').read_text()
    assert 'Sleeper games' in html and 'Yahoo games' not in html
    assert report.to_dict()['meta']['provider'] == 'sleeper'
    run = dict(provider='sleeper', year=2026, league_id='123', nickname='Test')
    assert publish.resolve_week(run, root, backfill=False, settings=None) == 2


def test_custom_score_remains_independent(tmp_path):
    client = Client()
    get = client.get
    def custom(path):
        data = get(path)
        if '/matchups/' in path:
            data[0]['custom_points'] = 50
        return data
    client.get = custom
    report = ReportProcessor(collect(tmp_path, client), 2)
    with pytest.raises(ValueError, match='could not be reconciled'):
        report.validate_reconciliation()


def test_reserves_are_eligible_bench_candidates(tmp_path):
    client = Client()
    client.league['settings']['reserve_slots'] = 1
    # Historical rosters may exceed the current roster limit.
    client.league['roster_positions'] = ['QB']
    get = client.get
    def with_reserve(path):
        data = get(path)
        if '/matchups/' in path:
            data[0]['players'].append('5')
            data[0]['players_points']['5'] = 40
        return data
    client.get = with_reserve
    report = ReportProcessor(collect(tmp_path, client), 2)
    report.validate_reconciliation()
    assert report.silver_lineups.query("team_id == '1'").optimal_points.tolist() == [40, 40]
    assert report.silver_lineups.query("team_id == '1'").yahoo_actual_points.tolist() == [40, 40]
    reserves = report.silver_player.query("player_id == '5'")
    assert reserves.roster_slot.eq('BN').all()
    assert reserves.is_optimal.all()
    assert not reserves.is_starting.any()


def test_unknown_taxi_slots_disable_optimization(tmp_path):
    client = Client()
    client.league['settings']['taxi_slots'] = 1
    report = ReportProcessor(collect(tmp_path, client), 2)
    report.validate_reconciliation()
    assert report.silver_lineups.optimal_points.isna().all()


def test_wrong_season_and_future_week_rejected(tmp_path):
    with pytest.raises(ValueError, match='belongs to'):
        sleeper.league_metadata(2025, '123', Client())
    with pytest.raises(ValueError, match='completed regular-season'):
        sleeper.backfill_season(2026, '123', 1, 3, settings=Settings(data_dir=tmp_path), league_nickname='Test', client=Client())


def test_weekly_coverage_and_missing_scores():
    client = Client()
    get = client.get
    client.get = lambda path: [{**r, 'week': 9} for r in get(path)]
    with pytest.raises(ValueError, match='incorrect weekly coverage'):
        sleeper.weekly_stats(client, 'stats', 2026, 1)
    assert sleeper.score(None, {'rec': .5}) is None
    assert sleeper.score({'stats': {'rec': 4, 'rec_yd': 55}}, {'rec': .5, 'rec_yd': .1}) == 7.5


def test_provider_validation(tmp_path):
    path = tmp_path / 'runs.json'
    run = dict(provider='sleeper', league_id='123', year=2026, nickname='Test')
    path.write_text(json.dumps([run]))
    assert publish.load_runs(path) == [run]
    path.write_text(json.dumps([{**run, 'provider': 'invalid'}]))
    with pytest.raises(ValueError, match='provider must be'):
        publish.load_runs(path)


def test_remote_week_selection(monkeypatch, tmp_path):
    client = Client()
    monkeypatch.setattr(sleeper, 'SleeperClient', lambda: client)
    assert publish.resolve_week(dict(provider='sleeper', year=2026, league_id='123', nickname='Test'),
                                tmp_path, backfill=True, settings=None) == 2
    client.league['settings']['last_scored_leg'] = 1
    assert sleeper.league_metadata(2026, '123', client)[0]['current_week'] == 2


def test_no_draft_and_missing_player_score(tmp_path):
    client = Client()
    get = client.get
    def missing(path):
        if path.endswith('/drafts'):
            return []
        data = get(path)
        if '/matchups/' in path:
            del data[0]['players_points']['1']
        return data
    client.get = missing
    report = ReportProcessor(collect(tmp_path, client), 2, simulation_count=10)
    assert report.silver_player.draft_pick.isna().all()
    assert report.silver_player.query("player_id == '1'").actual_points.isna().all()
    assert report.silver_reconciliation.query("team_id == '1'").status.eq('missing_player_points_or_roster').all()
    report.to_dict()


def test_empty_starter_and_archive_collision(tmp_path):
    client = Client()
    get = client.get
    def empty(path):
        data = get(path)
        if '/matchups/' in path:
            data[0]['starters'] = ['0']
            data[0]['points'] = 0
        return data
    client.get = empty
    root = collect(tmp_path, client)
    report = ReportProcessor(root, 2)
    report.validate_reconciliation()
    assert report.silver_lineups.query("team_id == '1'").optimal_points.isna().all()
    path = root / 'metadata.json'
    metadata = json.loads(path.read_text())
    metadata['provider'] = 'yahoo'
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='different league/provider'):
        collect(tmp_path, client)


def test_publish_routes_sleeper(tmp_path, monkeypatch):
    import sys
    from yahoo_fantasy_data import yahoo
    client = Client()
    monkeypatch.setattr(sleeper, 'SleeperClient', lambda: client)
    monkeypatch.setattr(yahoo, 'backfill_season', lambda *a, **kw: pytest.fail('Yahoo must not collect Sleeper leagues'))
    config = tmp_path / 'runs.json'
    config.write_text(json.dumps([dict(provider='sleeper', year=2026, league_id='123', nickname='Test', template='both', strict=True)]))
    monkeypatch.setattr(sys, 'argv', ['publish', '--config', str(config), '--data-dir', str(tmp_path / 'data'),
                                   '--docs-dir', str(tmp_path / 'docs'), '--backfill'])
    publish.main()
    assert len(list((tmp_path / 'docs').glob('*.html'))) == 2
    assert len(list((tmp_path / 'docs').rglob('*.csv.gz'))) == 2


def test_refresh_latest_reuses_older_snapshots(tmp_path):
    root = collect(tmp_path)
    first = root / 'team_data/team_data_week_1.csv.gz'
    before = first.stat().st_mtime_ns
    statuses = sleeper.backfill_season(2026, '123', 1, 2, settings=Settings(data_dir=tmp_path),
                                      league_nickname='Test', client=Client())
    assert set(statuses[1].values()) == {'skipped'}
    assert set(statuses[2].values()) == {'written'}
    assert first.stat().st_mtime_ns == before
