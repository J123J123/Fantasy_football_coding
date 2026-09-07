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
    history.write_text(json.dumps({'One': {'2025': '1'}, 'Two': {'2025': '2'}}))
    docs = tmp_path / 'docs'
    real_processor = publish.ReportProcessor
    monkeypatch.setattr(publish, 'ReportProcessor', lambda *args: real_processor(archive, 2, simulation_count=10))
    monkeypatch.setattr(sys, 'argv', ['publish', '--season', '2025', '--week', '2',
                                   '--league-history', str(history), '--docs-dir', str(docs)])
    publish.main()
    assert len(list(docs.glob('*.html'))) == 3
    assert len(list(docs.rglob('*.csv.gz'))) == 4


def test_backfill_failure_stops_publication(tmp_path, monkeypatch):
    from yahoo_fantasy_data import yahoo
    history = tmp_path / 'history.json'
    history.write_text(json.dumps({'One': {'2025': '1'}}))
    monkeypatch.setattr(yahoo, 'backfill_season', lambda *a, **kw: {1: {'player_data': 'authentication_required'}})
    docs = tmp_path / 'docs'
    monkeypatch.setattr(sys, 'argv', ['publish', '--season', '2025', '--week', '1', '--backfill',
                                   '--league-history', str(history), '--docs-dir', str(docs)])
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
