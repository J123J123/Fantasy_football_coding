"""Historical normal-score approximation of the legacy expected-win blend."""
import math
import pandas as pd
from .common import ratio, win, total, section, NAN, ranked
WEIGHTS={'expected_wins':.8,'actual_vs_opp_avg':.075,'avg_vs_opp_actual':.075,'avg_vs_opp_avg':.05}


def build(processor):
    games=processor.silver_team_week
    stats={team:(g.actual_points.mean(),g.actual_points.std(ddof=1)) if g.actual_points.notna().all() else (NAN,NAN)
           for team,g in games.groupby('team_id')}
    rows=[]
    for team,g in games.groupby('team_id'):
        mean,sd=stats[team]; probs={}; aa=[]; ao=[]; mm=[]
        for r in g.itertuples():
            om,os=stats.get(r.opponent_id,(NAN,NAN))
            scale=math.sqrt(sd**2+os**2)
            # Weekly observed margin measured against historical combined volatility.
            margin=r.actual_points-r.opponent_points
            p=.5*(1+math.erf(margin/scale/math.sqrt(2))) if scale>0 else win(r.actual_points,r.opponent_points) if scale==0 else NAN
            probs[str(r.week)]=p
            aa.append(win(r.actual_points,om)); ao.append(win(mean,r.opponent_points)); mm.append(win(mean,om))
        values=dict(expected_wins=total(probs.values()),actual_vs_opp_avg=total(aa),
                    avg_vs_opp_actual=total(ao),avg_vs_opp_avg=total(mm))
        actual=total(g.win)
        rows.append(dict(team_id=team,weekly_probability=probs,**values,actual_wins=actual,
                         ratio=ratio(actual,sum(values[k]*v for k,v in WEIGHTS.items()))))
    return ranked(pd.DataFrame(rows),'ratio')


def payload(processor, table):
    return section(table,'Actual wins divided by a weighted expected-win blend. Weekly probability uses observed margin and combined historical score standard deviations (normal approximation).',
                   weights=WEIGHTS,weeks=sorted(processor.silver_team_week.week.unique().tolist()))
