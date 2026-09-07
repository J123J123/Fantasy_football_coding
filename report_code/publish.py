"""Build the report/download site from local archives, optionally backfilling first."""
import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote

from . import ReportProcessor


def export_silver(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('player', 'schedule'):
        # Fixed gzip header makes identical exports byte-for-byte reproducible.
        with (directory / f'silver_{name}.csv.gz').open('wb') as stream:
            getattr(report, f'silver_{name}').to_csv(
                stream, index=False, compression={'method': 'gzip', 'mtime': 0})


def build_index(docs):
    docs = Path(docs)
    rows = []
    for path in sorted(docs.rglob('*')):
        if not path.is_file() or path.name.startswith('.') or path == docs / 'index.html':
            continue
        relative = path.relative_to(docs).as_posix()
        href = quote(relative)
        label = html.escape(relative)
        report = path.suffix == '.html'
        actions = f'<a href="{href}" {"" if report else "download"}>{"Open report" if report else "Download"}</a>'
        if path.name.endswith('.csv.gz'):
            actions += f' <a href="{href}" class="unzip" download="{html.escape(path.name[:-3])}">Download CSV (unzip)</a>'
        rows.append(f'<li data-kind="{"report" if report else "data"}"><div><span class="tag">{"REPORT" if report else "DATA"}</span><h2>{label}</h2><small>{path.stat().st_size / 1024:,.1f} KB</small></div><nav aria-label="{label}">{actions}</nav></li>')
    template = Path(__file__).parents[1] / 'report_template' / 'index.html'
    (docs / 'index.html').write_text(template.read_text().replace('<!-- FILES -->', '\n'.join(rows)), encoding='utf-8')


def load_runs(path):
    """Validate every run before collecting data or writing reports."""
    from yahoo_fantasy_data.config import storage_league_name
    runs = json.loads(Path(path).read_text())
    if not isinstance(runs, list) or not runs:
        raise ValueError('Run configuration must be a nonempty JSON list')
    destinations = set()
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError('Each run must be a JSON object')
        unknown = set(run) - {'league_id', 'year', 'nickname', 'week', 'enabled',
                              'overwrite', 'strict', 'template'}
        if unknown:
            raise ValueError(f'Unknown run fields: {sorted(unknown)}')
        if type(run.get('year')) is not int or not 2000 <= run['year'] <= 2100:
            raise ValueError('Each run needs an integer year between 2000 and 2100')
        if not isinstance(run.get('league_id'), (str, int)) or isinstance(run['league_id'], bool) or not str(run['league_id']).isdigit():
            raise ValueError('Each run needs a numeric league_id (prefer a JSON string)')
        if not isinstance(run.get('nickname'), str) or not run['nickname'].strip():
            raise ValueError('Each run needs a nonempty nickname')
        if run.get('week') is not None and (type(run['week']) is not int or not 1 <= run['week'] <= 18):
            raise ValueError('Optional week must be an integer from 1 to 18')
        for option in ('enabled', 'overwrite', 'strict'):
            if option in run and type(run[option]) is not bool:
                raise ValueError(f'{option} must be a JSON boolean')
        if run.get('template', 'original') not in ('original', 'pc'):
            raise ValueError('template must be original or pc')
        folder = storage_league_name(run['nickname'], str(run['league_id']))
        destination = (folder, run['year'])
        if run.get('enabled', True):
            if destination in destinations:
                raise ValueError(f'Duplicate league/year output: {destination}')
            destinations.add(destination)
    return [run for run in runs if run.get('enabled', True)]


def resolve_week(run, data_path, *, backfill, settings):
    if run.get('week') is not None:
        return run['week']
    if not backfill:
        metadata = json.loads((data_path / 'metadata.json').read_text())
        week = metadata.get('last_collected_week')
        if week is None:
            raise ValueError(f'{data_path}: last_collected_week is missing; configure week explicitly')
        week = int(week)
    else:
        from yahoo_fantasy_data.yahoo import league_metadata
        from yahoo_fantasy_data.utils import first_value
        payload, *_ = league_metadata(run['year'], str(run['league_id']), settings)
        end = first_value(payload, 'end_week')
        finished = str(first_value(payload, 'is_finished', '0')).lower() in ('1', 'true')
        current = first_value(payload, 'current_week')
        if finished and end is not None:
            week = int(end)
        elif not finished and current is not None:
            week = max(0, int(current) - 1)
            if end is not None:
                week = min(week, int(end))
        else:
            raise ValueError(f"{run['nickname']}: Yahoo week metadata is missing; configure week explicitly")
    if not 0 <= week <= 18:
        raise ValueError(f'Inferred week {week} is outside 0–18')
    return week


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('report_runs.json'))
    parser.add_argument('--week', type=int, help='Override the inferred/configured week for all selected runs')
    parser.add_argument('--leagues', nargs='+', help='Filter configured runs by nickname')
    parser.add_argument('--data-dir', type=Path, default=Path('yahoo-fantasy-data/data'))
    parser.add_argument('--docs-dir', type=Path, default=Path('docs'))
    parser.add_argument('--backfill', action='store_true')
    parser.add_argument('--overwrite', action='store_true', help='Refresh snapshots for all selected runs')
    parser.add_argument('--strict', action='store_true', help='Require official score reconciliation for all runs')
    parser.add_argument('--template', choices=['original', 'pc'], help='Override configured report wording')
    args = parser.parse_args()
    if args.week is not None and not 1 <= args.week <= 18:
        parser.error('--week must be between 1 and 18')
    try:
        runs = load_runs(args.config)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.leagues:
        unknown = set(args.leagues) - {run['nickname'] for run in runs}
        if unknown:
            parser.error(f'Unknown or disabled nicknames: {sorted(unknown)}')
        runs = [run for run in runs if run['nickname'] in args.leagues]
    if not runs:
        parser.error('No enabled runs configured')
    from yahoo_fantasy_data.config import load_settings, storage_league_name
    from yahoo_fantasy_data.yahoo import backfill_season
    settings = load_settings(args.data_dir)
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    for run in runs:
        name, year = run['nickname'], run['year']
        folder = storage_league_name(name, str(run['league_id']))
        data_path = args.data_dir / folder / str(year)
        week = args.week if args.week is not None else resolve_week(
            run, data_path, backfill=args.backfill, settings=settings)
        if week == 0:
            print(f'Skipping {name}, {year}: no completed weeks yet', flush=True)
            continue
        print(f'Building {name}, {year}, week {week}', flush=True)
        if args.backfill:
            statuses = backfill_season(year, str(run['league_id']), 1, week,
                                       args.overwrite or run.get('overwrite', False),
                                       settings=settings, league_nickname=name)
            failures = {week: results for week, results in statuses.items()
                        if any(value.startswith('failed:') or value == 'authentication_required'
                               for value in results.values())}
            if failures:
                raise RuntimeError(f'Incomplete backfill for {name}: {failures}')
        report = ReportProcessor(data_path, week)
        if args.strict or run.get('strict', False):
            report.validate_reconciliation()
        report.write_html(args.docs_dir / f'{folder}_{year}_week{week}.html',
                          template=args.template or run.get('template', 'original'))
        export_silver(report, args.docs_dir / 'data' / folder / str(year) / f'week{week}')
        print(f'Saved {name} report and silver tables', flush=True)
    build_index(args.docs_dir)
    print(f'Updated {args.docs_dir / "index.html"}', flush=True)


if __name__ == '__main__':
    main()
