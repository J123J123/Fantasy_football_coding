import pandas as pd
from .common import section, NAN, total


def build(processor):
    players=processor.silver_player
    counts={}
    for (team,week),g in players[players.is_starting & players.team_id.notna()].groupby(['team_id','week']):
        counts[team,week] = (int(g.is_stud.sum()),int(g.is_dud.sum())) if g.volatility_known.all() else (NAN,NAN)
    rows=[]
    for team,g in processor.silver_team_week.groupby('team_id'):
        own=[counts.get((team,r.week),(NAN,NAN)) if pd.notna(r.actual_points) else (NAN,NAN) for r in g.itertuples()]
        opp=[counts.get((r.opponent_id,r.week),(NAN,NAN)) if pd.notna(r.opponent_points) else (NAN,NAN) for r in g.itertuples()]
        s,d=total(x[0] for x in own),total(x[1] for x in own)
        so,do=total(x[0] for x in opp),total(x[1] for x in opp)
        rows.append(dict(team_id=team,studs=s,duds=d,studded_on=so,dudded_on=do,s2d_diff=s-so-d+do))
    return pd.DataFrame(rows)


def payload(processor, table):
    return section(table,'Starters only. Stud: more than twice projection and at least 20 points. Dud: at most 25% of projection with a projection of at least 10.')
