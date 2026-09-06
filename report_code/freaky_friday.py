import pandas as pd
from .common import total, win
from .processor import records


def build(processor):
    games = processor.silver_team_week.set_index(['team_id','week'])
    rows = []
    for team in processor.teams.team_id:
        for other in processor.teams.team_id:
            swap, head = [], []
            for week in sorted(games.index.get_level_values('week').unique()):
                mine, theirs = games.loc[(team,week)], games.loc[(other,week)]
                # A true body swap replaces a self-opponent with the schedule owner's score.
                opponent = theirs.actual_points if pd.notna(theirs.opponent_id) and theirs.opponent_id == team else theirs.opponent_points
                swap.append(win(mine.actual_points, opponent))
                head.append(0 if team == other else win(mine.actual_points, theirs.actual_points))
            rows.append(dict(team_id=team, schedule_team_id=other, schedule_wins=total(swap), head_to_head_wins=total(head)))
    return pd.DataFrame(rows)


def payload(processor, table):
    def matrix(column):
        return {team: dict(zip(g.schedule_team_id, g[column])) for team,g in table.groupby('team_id')}
    summary = table.groupby('team_id').schedule_wins.agg(total=total, max='max', avg='mean', min='min').reset_index()
    for team,g in table.groupby('team_id'):
        if g.schedule_wins.isna().any(): summary.loc[summary.team_id.eq(team), ['max','avg','min']] = float('nan')
    summary['rank'] = summary.total.rank(method='min',ascending=False)
    return {'description': 'Wins with each other manager’s schedule. Self-opponents are replaced by the schedule owner; ties count as half a win.',
            'schedule_swap': {'matrix': matrix('schedule_wins'), 'summary': records(summary)},
            'head_to_head': {'matrix': matrix('head_to_head_wins')}}
