import json
import sys

import pandas as pd
import pytest

from report_code import publish
from report_code.tests.test_processor import archive


def test_silver_roundtrip_and_reproducibility(archive, tmp_path):
    report = publish.ReportProcessor(archive, 2)
    destination = tmp_path / 'exports'
    publish.export_silver(report, destination)
    path = destination / 'silver_player.csv.gz'
    original = path.read_bytes()
    players = pd.read_csv(path)
    assert len(players) == 16
    assert players.week.max() == 2
    assert players.actual_points.notna().all()
    assert len(pd.read_csv(destination / 'silver_schedule.csv.gz')) > 0
    publish.export_silver(report, destination)
    assert path.read_bytes() == original


def test_index_links_escape_and_discover_files(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'a & b.csv.gz').write_bytes(b'example')
    (tmp_path / 'report.html').write_text('example')
    publish.build_index(tmp_path)
    result = (tmp_path / 'index.html').read_text()
    assert 'data/a%20%26%20b.csv.gz' in result
    assert 'a &amp; b.csv.gz' in result
    assert 'download="a &amp; b.csv"' in result
    assert 'href="report.html"' in result
    assert 'href="index.html"' not in result
    assert '<!-- FILES -->' not in result


def test_multiple_leagues_publish(archive, tmp_path, monkeypatch):
    history = tmp_path / 'history.json'
    history.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One'}, {'league_id': '2', 'year': 2024, 'nickname': 'Two'}]))
    docs = tmp_path / 'docs'
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda *args: real_processor(archive, 2, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--week', '2',
                                   '--config', str(history), '--docs-dir', str(docs)])
    publish.main()
    assert len(list(docs.glob('*.html'))) == 3
    assert len(list(docs.rglob('*.csv.gz'))) == 4


def test_backfill_failure_stops_publication(tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    history = tmp_path / 'history.json'
    history.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One'}]))
    monkeypatch.setattr(yahoo, 'backfill_season', lambda *a, **kw: {1: {'player_data': 'authentication_required'}})
    docs = tmp_path / 'docs'
    monkeypatch.setattr(sys, 'argv', ['publish', '--week', '1', '--backfill',
                                   '--config', str(history), '--docs-dir', str(docs)])
    with pytest.raises(RuntimeError, match='Incomplete backfill'):
        publish.main()
    assert not list(docs.rglob('*.html'))


def test_single_league_silver_only_cli(archive, tmp_path, monkeypatch, capsys):
    from report_code.__main__ import main
    destination = tmp_path / 'silver-only'
    monkeypatch.setattr(sys, 'argv', ['report_code', str(archive), '--week', '2',
                                    '--silver-dir', str(destination)])
    main()
    assert len(pd.read_csv(destination / 'silver_player.csv.gz')) == 16
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('payload, expected', [
    ({'current_week': '5', 'end_week': '17'}, 4),
    ({'current_week': '17', 'end_week': '17', 'is_finished': '1'}, 17),
    ({'current_week': '1', 'end_week': '17'}, 0),
    ({'current_week': '0', 'end_week': '17'}, 0),
    ({'current_week': '19', 'end_week': '17'}, 17),
])
def test_infer_remote_week(payload, expected, tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: (payload, None, None, None, None))
    run = {'year': 2025, 'league_id': '1', 'nickname': 'One'}
    assert publish.resolve_week(run, tmp_path, backfill=True, settings=None) == expected


def test_local_inference_and_explicit_week(archive):
    run = {'year': 2025, 'league_id': '1', 'nickname': 'One'}
    # Last collected week wins over the archive's stale current_week.
    assert publish.resolve_week(run, archive, backfill=False, settings=None) == 3
    assert publish.resolve_week({**run, 'week': 1}, archive, backfill=True, settings=None) == 1


def test_missing_remote_week_fails(tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: ({'end_week': 17}, None, None, None, None))
    with pytest.raises(ValueError, match='metadata is missing'):
        publish.resolve_week({'year': 2025, 'league_id': '1', 'nickname': 'One'},
                             tmp_path, backfill=True, settings=None)


@pytest.mark.parametrize('change', [{'week': 0}, {'week': True}, {'year': '2025'},
                                   {'enabled': 'false'}, {'template': 'bad'}, {'typo': 1}])
def test_invalid_run_config(tmp_path, change):
    path = tmp_path / 'runs.json'
    path.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One', **change}]))
    with pytest.raises(ValueError):
        publish.load_runs(path)


def test_config_years_disabled_and_collisions(tmp_path):
    path = tmp_path / 'runs.json'
    run = {'league_id': '1', 'year': 2025, 'nickname': 'One'}
    path.write_text(json.dumps([run, {**run, 'year': 2024}, {**run, 'enabled': False}]))
    assert len(publish.load_runs(path)) == 2
    path.write_text(json.dumps([run, run]))
    with pytest.raises(ValueError, match='Duplicate'):
        publish.load_runs(path)


def test_default_config_local_build_without_week(archive, tmp_path, monkeypatch):
    import shutil
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'report_runs.json').write_text(json.dumps([
        {'league_id': '1', 'year': 2025, 'nickname': 'One', 'template': 'pc'}]))
    destination = tmp_path / 'data' / 'One' / '2025'
    shutil.copytree(archive, destination)
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda path, week: real_processor(path, week, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--data-dir', 'data'])
    publish.main()
    assert (tmp_path / 'docs/One_2025_week3.html').exists()
    assert pd.read_csv(tmp_path / 'docs/data/One/2025/week3/silver_player.csv.gz').week.max() == 3


def test_backfill_uses_inferred_week_and_config_options(archive, tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    run = {'league_id': '9', 'year': 2024, 'nickname': 'One', 'overwrite': True}
    config = tmp_path / 'runs.json'
    config.write_text(json.dumps([run]))
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: ({'current_week': 3, 'end_week': 17}, None, None, None, None))
    calls = []
    def backfill(*args, **kwargs):
        calls.append((args, kwargs))
        return {1: {'player_data': 'written'}, 2: {'player_data': 'written'}}
    monkeypatch.setattr(yahoo, 'backfill_season', backfill)
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda path, week: real_processor(archive, week, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--config', str(config), '--backfill', '--docs-dir', str(tmp_path / 'docs')])
    publish.main()
    assert calls[0][0] == (2024, '9', 1, 2, True)
    assert calls[0][1]['league_nickname'] == 'One'
    assert (tmp_path / 'docs/One_2024_week2.html').exists()
