import pandas as pd
from .boned_detail import detail
from .common import ratio
from .processor import records


def build(processor):
    rows = []
    for week in range(2, processor.current_week + 1):
        for team, g in detail(processor, week).groupby('team_id'):
            value = (ratio(g.opponent_score.mean(), g.opponent_avg.mean()) - 1) * 100 if g[['opponent_score','opponent_avg']].notna().all().all() else float('nan')
            rows.append({'team_id': team, 'week': week, 'value': value})
    out = pd.DataFrame(rows, columns=['team_id','week','value'])
    out['rank'] = out.groupby('week').value.rank(method='min')
    return out


def payload(processor, table):
    rows = []
    for team in processor.teams.team_id:
        g = table[table.team_id == team].sort_values('week')
        rows.append({'team_id': team, 'values': dict(zip(g.week.astype(str), g.value)),
                     'ranks': dict(zip(g.week.astype(str), g['rank'])),
                     'difference': g.value.iloc[-1] - g.value.iloc[-2] if len(g)>1 else None,
                     'rank_delta': g['rank'].iloc[-1] - g['rank'].iloc[-2] if len(g)>1 else None})
    return {'description': 'Percent above or below opponents’ scoring average against everyone else. Lower ranks indicate easier scoring luck.',
            'weeks': sorted(table.week.unique().tolist()), 'rows': rows}
