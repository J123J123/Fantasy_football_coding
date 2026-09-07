"""Run from the repository root: python -m report_code DATA --week 5 --html report.html."""
import argparse
import json
from pathlib import Path
from . import ReportProcessor


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data_path')
    p.add_argument('--week',type=int)
    p.add_argument('--json',dest='json_path')
    p.add_argument('--html')
    p.add_argument('--silver-dir', help='Export silver player and schedule tables as CSV.gz')
    p.add_argument('--template', choices=('original', 'pc'), default='original',
                   help='HTML wording: original (default) or work-appropriate pc')
    p.add_argument('--official-scores')
    p.add_argument('--strict',action='store_true',help='Require official score reconciliation before export')
    p.add_argument('--playoff-teams',type=int)
    p.add_argument('--playoff-byes',type=int)
    p.add_argument('--divisions',help='JSON file mapping team IDs to division names')
    args=p.parse_args()
    report=ReportProcessor(args.data_path,args.week,official_scores_path=args.official_scores,
                           playoff_teams=args.playoff_teams,playoff_byes=args.playoff_byes,
                           divisions=json.loads(Path(args.divisions).read_text()) if args.divisions else None)
    if args.strict: report.validate_reconciliation()
    if args.json_path: report.to_json(args.json_path)
    if args.html: report.write_html(args.html, template=args.template)
    if args.silver_dir:
        from .publish import export_silver
        export_silver(report, args.silver_dir)
    if not args.json_path and not args.html and not args.silver_dir: print(report.to_json())


if __name__=='__main__': main()
