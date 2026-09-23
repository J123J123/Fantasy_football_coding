"""Standings through the report week, derived from scored matchups."""
import pandas as pd
from .common import total, ratio
from .processor import records


def payload(processor):
    divisions = processor.divisions
    names = {}
    if divisions and processor._divisions_override is None:
        frame = processor.silver_divisions.dropna(subset=['division_id', 'division_name'])
        names = dict(zip(frame.division_id.astype(str), frame.division_name))
    rows = []
    for team, games in processor.silver_team_week.groupby('team_id'):
        # A missing opponent is a bye, not a loss or an unknown matchup.
        matchups = games[games.opponent_id.notna()]
        def record(group):
            known = group.win.notna().all()
            return {name: int(group.win.eq(value).sum()) if known else None
                    for name, value in [('wins', 1), ('losses', 0), ('ties', .5)]}
        row = dict(team_id=team, **record(matchups), points_for=total(games.actual_points),
                   points_against=total(matchups.opponent_points) if len(matchups) else 0,
                   win_pct=ratio(total(matchups.win), len(matchups)))
        division = divisions.get(str(team))
        row.update(division_id=division, division_name=names.get(division, f'Division {division}') if division else None)
        if division is not None:
            divisional = matchups[matchups.opponent_id.astype(str).map(divisions).eq(division)]
            row.update({f'division_{key}': value for key, value in record(divisional).items()})
        rows.append(row)
    table = pd.DataFrame(rows).sort_values(['win_pct', 'points_for', 'team_id'], ascending=[False, False, True], na_position='last')
    def ranks(group):
        result = pd.Series(index=group.index, dtype=float)
        previous = None
        rank = None
        for position, (index, row) in enumerate(group.iterrows(), 1):
            if pd.isna(row.win_pct) or pd.isna(row.points_for):
                continue
            score = (row.win_pct, row.points_for)
            if score != previous:
                rank = position
            result.loc[index] = rank
            previous = score
        return result
    table['overall_rank'] = ranks(table)
    table['division_rank'] = float('nan')
    if divisions:
        for _, group in table.groupby('division_id'):
            table.loc[group.index, 'division_rank'] = ranks(group)
    return {'rows': records(table), 'has_divisions': bool(divisions),
            'description': 'Standings through the report week, ordered by win percentage (ties count as half a win), then points for. Division rank is position within the division; overall rank is position across the league. Equal win percentage and points for share a rank. Division records count only games against teams in the same division. Points are calculated from actual starters; unavailable results remain blank. This ordering does not apply every league-specific tiebreaker.'}
