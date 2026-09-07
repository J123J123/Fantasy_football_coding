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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', required=True, type=int)
    parser.add_argument('--week', required=True, type=int, help='Last completed week to collect and report')
    parser.add_argument('--leagues', nargs='+', help='Nicknames from league-history; default: all in season')
    parser.add_argument('--league-history', type=Path, default=Path('yahoo-fantasy-data/league_history.json'))
    parser.add_argument('--data-dir', type=Path, default=Path('yahoo-fantasy-data/data'))
    parser.add_argument('--docs-dir', type=Path, default=Path('docs'))
    parser.add_argument('--backfill', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--strict', action='store_true', help='Require official score reconciliation')
    parser.add_argument('--template', choices=['original', 'pc'], default='original')
    args = parser.parse_args()
    if not 1 <= args.week <= 18:
        parser.error('--week must be between 1 and 18')
    history = json.loads(args.league_history.read_text())
    leagues = args.leagues or [name for name, seasons in history.items() if str(args.season) in seasons]
    if not leagues:
        parser.error('No leagues configured for this season; update league_history.json')
    for name in leagues:
        if name not in history or str(args.season) not in history[name]:
            parser.error(f'No league ID for {name} in {args.season}')
    from yahoo_fantasy_data.config import load_settings, storage_league_name
    from yahoo_fantasy_data.yahoo import backfill_season
    folders = [storage_league_name(name, history[name][str(args.season)]) for name in leagues]
    if len(set(folders)) != len(folders):
        parser.error('League nicknames resolve to duplicate output directories')
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    for name, folder in zip(leagues, folders):
        print(f'Building {name}, {args.season}, week {args.week}', flush=True)
        if args.backfill:
            statuses = backfill_season(args.season, str(history[name][str(args.season)]),
                                       1, args.week, args.overwrite,
                                       settings=load_settings(args.data_dir), league_nickname=name)
            failures = {week: results for week, results in statuses.items()
                        if any(value.startswith('failed:') or value == 'authentication_required'
                               for value in results.values())}
            if failures:
                raise RuntimeError(f'Incomplete backfill for {name}: {failures}')
        report = ReportProcessor(args.data_dir / folder / str(args.season), args.week)
        if args.strict:
            report.validate_reconciliation()
        report.write_html(args.docs_dir / f'{folder}_{args.season}_week{args.week}.html', template=args.template)
        export_silver(report, args.docs_dir / 'data' / folder / str(args.season) / f'week{args.week}')
        print(f'Saved {name} report and silver tables', flush=True)
    build_index(args.docs_dir)
    print(f'Updated {args.docs_dir / "index.html"}', flush=True)


if __name__ == '__main__':
    main()
