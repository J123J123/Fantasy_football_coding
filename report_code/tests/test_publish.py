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


def test_multiple_leagues_publish(archive, tmp_path, monkeypatch):
    history = tmp_path / 'history.json'
    history.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One'}, {'league_id': '2', 'year': 2024, 'nickname': 'Two'}]))
    docs = tmp_path / 'docs'
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda *args: real_processor(archive, 2, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--week', '2',
                                   '--config', str(history), '--docs-dir', str(docs)])
    publish.main()
    assert len(list(docs.glob('*.html'))) == 2
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
    ({'current_week': '5', 'playoff_start_week': '15'}, 5),
    ({'current_week': '17', 'playoff_start_week': '15', 'is_finished': '1'}, 14),
    ({'current_week': '14', 'playoff_start_week': '15'}, 14),
    ({'current_week': '15', 'playoff_start_week': '15'}, 14),
    ({'current_week': '1', 'playoff_start_week': '15'}, 1),
    ({'current_week': '0'}, 0),
    ({'current_week': '19', 'playoff_start_week': '16'}, 15),
    ({'current_week': '19', 'uses_playoff': '0', 'end_week': '18'}, 18),
])
def test_infer_remote_week(payload, expected, tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: (payload, None, None, None, None))
    run = {'year': 2025, 'league_id': '1', 'nickname': 'One'}
    assert publish.resolve_week(run, tmp_path, backfill=True, settings=None) == expected


def test_local_inference_and_explicit_week(archive):
    run = {'year': 2025, 'league_id': '1', 'nickname': 'One'}
    # Use metadata current_week, not last_collected_week.
    assert publish.resolve_week(run, archive, backfill=False, settings=None) == 2
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
    assert (tmp_path / 'docs/One_2025_week2_pc.html').exists()
    assert pd.read_csv(tmp_path / 'docs/data/One/2025/silver_player.csv.gz').week.max() == 2


def test_backfill_uses_inferred_week_and_config_options(archive, tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    run = {'league_id': '9', 'year': 2024, 'nickname': 'One', 'overwrite': True}
    config = tmp_path / 'runs.json'
    config.write_text(json.dumps([run]))
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: ({'current_week': 3, 'end_week': 17, 'playoff_start_week': 15}, None, None, None, None))
    calls = []
    def backfill(*args, **kwargs):
        calls.append((args, kwargs))
        return {1: {'player_data': 'written'}, 2: {'player_data': 'written'}}
    monkeypatch.setattr(yahoo, 'backfill_season', backfill)
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda path, week: real_processor(archive, week, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--config', str(config), '--backfill', '--docs-dir', str(tmp_path / 'docs')])
    publish.main()
    assert calls[0][0] == (2024, '9', 1, 3, True)
    assert calls[0][1]['league_nickname'] == 'One'
    assert (tmp_path / 'docs/One_2024_week3.html').exists()


@pytest.mark.parametrize('template, expected', [
    ('original', {'One_2025_week2.html'}),
    ('pc', {'One_2025_week2_pc.html'}),
    ('both', {'One_2025_week2.html', 'One_2025_week2_pc.html'}),
])
def test_weekly_reports_latest_data_and_template_override(archive, tmp_path, monkeypatch, template, expected):
    config = tmp_path / 'runs.json'
    config.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One', 'template': 'both'}]))
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'index.html').write_text('unchanged dynamic index')
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda *a: real_processor(archive, 2, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--week', '2', '--config', str(config),
                                    '--docs-dir', str(docs), '--template', template])
    publish.main()
    assert {p.name for p in docs.glob('One_2025*.html')} == expected
    data = docs / 'data/One/2025/silver_player.csv.gz'
    assert pd.read_csv(data).week.max() == 2
    data.write_bytes(b'replace me')
    for name in expected:
        (docs / name).write_text('replace me')
    publish.main()
    assert pd.read_csv(data).week.max() == 2
    assert len(list(docs.rglob('*.csv.gz'))) == 2
    for name in expected:
        assert (docs / name).read_text() != 'replace me'
    assert (docs / 'index.html').read_text() == 'unchanged dynamic index'
    # A later report week adds HTML while replacing the same two data exports.
    sys.argv[sys.argv.index('--week') + 1] = '3'
    publish.main()
    assert {p.name for p in docs.glob('One_2025*.html')} == expected | {
        name.replace('week2', 'week3') for name in expected}
    assert len(list(docs.rglob('*.csv.gz'))) == 2
    assert not list((docs / 'data').rglob('week*'))



def test_both_config(tmp_path):
    config = tmp_path / 'runs.json'
    config.write_text(json.dumps([{'league_id': '1', 'year': 2025, 'nickname': 'One', 'template': 'both'}]))
    assert publish.load_runs(config)[0]['template'] == 'both'


def test_single_report_cli_both(archive, tmp_path, monkeypatch):
    from report_code.__main__ import main
    output = tmp_path / 'report.html'
    monkeypatch.setattr(sys, 'argv', ['report_code', str(archive), '--week', '2',
                                    '--html', str(output), '--template', 'both'])
    main()
    assert output.exists()
    assert (tmp_path / 'report_pc.html').exists()
    assert output.read_text() != (tmp_path / 'report_pc.html').read_text()


def test_notebook_direct_public_backfill_and_gzip(archive, tmp_path, monkeypatch):
    from pathlib import Path
    from yahoo_fantasy_data import config, yahoo
    import report_code
    notebook = json.loads((Path(__file__).parents[2] / 'Notebook_Runner.ipynb').read_text())
    (tmp_path / 'report_code').mkdir()
    (tmp_path / 'report_code/processor.py').touch()
    monkeypatch.chdir(tmp_path)
    def forbidden(*a, **kw):
        raise AssertionError('Notebook must not load environment settings')
    monkeypatch.setattr(config, 'load_settings', forbidden)
    monkeypatch.setenv('YAHOO_CLIENT_ID', 'must-not-be-used')
    calls = []
    def backfill(**kwargs):
        calls.append(kwargs)
        assert not kwargs['settings'].oauth_configured
        assert kwargs['settings'].client_id is None
        return {1: {'player_data': 'written'}}
    monkeypatch.setattr(yahoo, 'backfill_season', backfill)
    monkeypatch.setattr(publish, 'resolve_week', lambda *a, **kw: 2)
    real_processor = report_code.ReportProcessor
    monkeypatch.setattr(report_code, 'ReportProcessor', lambda *a: real_processor(archive, 2, simulation_count=10))
    ns = {'LEAGUES': [{'nickname': 'One', 'league_id': '1', 'year': 2025, 'template': 'both'}]}
    exec(compile(''.join(notebook['cells'][1]['source']), 'notebook-cell-2', 'exec'), ns)
    assert len(calls) == 1
    assert (tmp_path / 'docs/One_2025_week2.html').exists()
    assert (tmp_path / 'docs/One_2025_week2_pc.html').exists()
    for table in ('player', 'schedule'):
        path = tmp_path / f'docs/data/One/2025/silver_{table}.csv.gz'
        assert path.read_bytes()[:2] == b'\x1f\x8b'
        assert not pd.read_csv(path).empty
    assert not list((tmp_path / 'docs').rglob('week*'))


def test_remote_week_reads_playoff_settings(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from yahoo_fantasy_data import yahoo
    provider = Mock()
    provider.settings.return_value = {'settings': {'playoff_start_week': '15'}}
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: (
        {'current_week': 17, 'end_week': 17}, None, provider, '461', '461.l.1'))
    assert publish.resolve_week({'year': 2025, 'league_id': '1', 'nickname': 'One'},
                                tmp_path, backfill=True, settings=None) == 14
    provider.settings.assert_called_once_with('461.l.1')


def test_local_week_caps_playoffs_and_requires_metadata(archive):
    path = archive / 'metadata.json'
    metadata = json.loads(path.read_text())
    metadata['current_week'] = 5
    path.write_text(json.dumps(metadata))
    run = {'year': 2025, 'league_id': '1', 'nickname': 'One'}
    assert publish.resolve_week(run, archive, backfill=False, settings=None) == 3
    del metadata['current_week']
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='current_week metadata is missing'):
        publish.resolve_week(run, archive, backfill=False, settings=None)


def test_missing_playoff_cutoff_fails(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from yahoo_fantasy_data import yahoo
    provider = Mock()
    provider.settings.return_value = {}
    monkeypatch.setattr(yahoo, 'league_metadata', lambda *a: (
        {'current_week': 17, 'end_week': 17}, None, provider, '461', '461.l.1'))
    with pytest.raises(ValueError, match='playoff_start_week'):
        publish.resolve_week({'year': 2025, 'league_id': '1', 'nickname': 'One'},
                             tmp_path, backfill=True, settings=None)


def test_collector_persists_current_week(tmp_path):
    from yahoo_fantasy_data.config import Settings
    from yahoo_fantasy_data.yahoo import update_metadata
    settings = Settings(data_dir=tmp_path)
    update_metadata(settings, 2025, '1', '461', '461.l.1',
                    {'current_week': '17', 'end_week': '17'}, 14, {})
    metadata = json.loads((tmp_path / '1/2025/metadata.json').read_text())
    assert metadata['current_week'] == '17'
    assert metadata['last_collected_week'] == 14
