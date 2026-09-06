import pandas as pd
from .common import NAN, total
from .processor import records
BUCKETS=['1-5','6-10','11-16','FA']


def bucket(row):
    rnd=row.get('draft_round')
    if pd.isna(row.team_id) or pd.isna(rnd) or pd.isna(row.get('draft_team_id')) or row.draft_team_id!=row.team_id: return 'FA'
    rnd=float(rnd)
    return '1-5' if rnd<=5 else '6-10' if rnd<=10 else '11-16' if rnd<=16 else '17+'


def build(processor):
    players=processor.silver_player.copy(); players['bucket']=players[['draft_round','draft_team_id','team_id']].apply(bucket,axis=1)
    rows=[]
    buckets=BUCKETS.copy()
    if players.bucket.eq('17+').any():
        players.loc[players.bucket.isin(['11-16','17+']),'bucket']='11+'
        buckets[2]='11+'
    for team in processor.teams.team_id:
        lineups=processor.silver_team_week.query('team_id == @team')[['team_id','week']].merge(
            processor.silver_lineups,on=['team_id','week'],how='left')
        for kind in ('historical','optimal'):
            valid=True
            if kind=='historical':
                g=players[players.team_id.eq(team)&players.is_starting]
                valid=processor.silver_reconciliation.query('team_id == @team').calculated_points.notna().all()
            else:
                indices=[]
                for value in lineups.optimal_player_indices:
                    if not isinstance(value,list): valid=False
                    else: indices.extend(value)
                g=players.loc[indices]
            valid=valid and g.actual_points.notna().all()
            values={b:float(g.loc[g.bucket.eq(b),'actual_points'].sum()) if valid else NAN for b in buckets}
            rows.append(dict(team_id=team,lineup=kind,values=values))
    return pd.DataFrame(rows)


def payload(processor, table):
    buckets=list(table.iloc[0]['values']) if len(table) else BUCKETS
    return {'description':'Points credited to the current manager’s own draft rounds. Players drafted by someone else count as FA (post-draft acquisitions).',
            'buckets':buckets,**{kind:records(table[table.lineup.eq(kind)].drop(columns='lineup')) for kind in ('historical','optimal')}}
