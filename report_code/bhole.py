import pandas as pd
from .common import total, win
from .processor import records
DELTAS = [-10, -5, -2.5, 0, 2.5, 5, 10]


def build(processor):
    rows=[]
    for team,g in processor.silver_team_week.groupby('team_id'):
        wins={str(d): total(win(r.actual_points+d,r.opponent_points) for r in g.itertuples()) for d in DELTAS}
        margin=(g.actual_points-g.opponent_points).abs()
        rows.append(dict(team_id=team,wins=wins,range=wins['10']-wins['-10'],
                         avg_width=margin.mean() if margin.notna().all() else None))
    return pd.DataFrame(rows)


def payload(processor, table):
    return {'description':'Wins after adding the indicated points each week; average width is the mean absolute matchup margin.',
            'deltas': DELTAS, 'rows': records(table)}
