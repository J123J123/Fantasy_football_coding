"""Opponent performance against everyone other than the focal manager."""
import pandas as pd
from .common import ratio
from .processor import records


def detail(processor, through):
    games = processor.silver_team_week.query('week <= @through')
    names = processor.teams.set_index('team_id').manager.to_dict()
    rows = []
    for game in games.itertuples():
        others = games[(games.team_id == game.opponent_id) & (games.opponent_id != game.team_id)]
        avg = others.actual_points.mean() if len(others) and others.actual_points.notna().all() else float('nan')
        rows.append(dict(team_id=game.team_id, week=game.week, opponent=names.get(game.opponent_id),
                         opponent_score=game.opponent_points, opponent_games=len(others),
                         opponent_avg=avg, ratio=ratio(game.opponent_points, avg)))
    return pd.DataFrame(rows)


def build(processor): return detail(processor, processor.current_week)


def payload(processor, table):
    managers = []
    for team, group in table.groupby('team_id'):
        avgs = {k: group[k].mean() if group[k].notna().all() else None
                for k in ('opponent_score', 'opponent_avg', 'ratio')}
        # Legacy display is ratio of average scores, not average of ratios.
        avgs['ratio'] = ratio(avgs['opponent_score'], avgs['opponent_avg'])
        managers.append({'team_id': team, 'rows': records(group.drop(columns='team_id')), 'averages': avgs})
    return {'description': 'Opponent scores compared with their games against other managers through the report week.',
            'managers': managers}
