import pandas as pd
from .common import NAN, total, ratio, win, section
from .lineups import optimize
from .vobl import weekly


def build(processor):
    players=processor.silver_player
    baseline=weekly(processor).groupby(['team_id','week']).baseline_points.agg(total)
    mob={}
    for week,g in players.groupby('week'):
        free=g[g.team_id.isna()]
        selected=optimize(free,processor.lineup_slots)
        mob[week]=total(free.loc[selected,'actual_points']) if selected is not None else NAN
    games=processor.silver_team_week.merge(processor.silver_lineups,on=['team_id','week'],how='left')
    rows=[]
    for team,g in games.groupby('team_id'):
        roster=players[players.team_id.eq(team)]
        archived=processor.bronze_team_data.query('team_id == @team')
        known=roster.volatility_known.all() and roster.week.nunique()==len(g) and len(roster)==len(archived)
        actual,optimal=total(g.actual_points),total(g.optimal_points)
        use=g[g.using_yahoo.eq(True)]; non=g[g.using_yahoo.eq(False)]
        decisions=g.using_yahoo.notna().all()
        eff_yes=ratio(total(use.actual_points),total(use.optimal_points))
        eff_no=ratio(total(non.actual_points),total(non.optimal_points))
        changes=[win(r.actual_points,r.opponent_points)-win(r.yahoo_actual_points,r.opponent_points) for r in g.itertuples()]
        changes_known=all(pd.notna(c) for c in changes)
        base=[baseline.get((team,r.week),NAN) for r in g.itertuples()]
        bench=[mob.get(r.week,NAN) for r in g.itertuples()]
        wins_added=sum(max(0,c) for c in changes) if changes_known else NAN
        losses_added=sum(min(0,c) for c in changes) if changes_known else NAN
        plums=ratio(eff_no,eff_yes)
        rows.append(dict(team_id=team,actual_points=actual,optimal_points=optimal,efficiency=ratio(actual,optimal),
                         using_yahoo_games=len(use) if decisions else NAN,using_yahoo_efficiency=eff_yes if decisions else NAN,
                         not_using_yahoo_games=len(non) if decisions else NAN,not_using_yahoo_efficiency=eff_no if decisions else NAN,
                         wins_added=wins_added,losses_added=losses_added,net_added=wins_added+losses_added,
                         sheep_pct=ratio(len(use),len(g)) if decisions else NAN,
                         plums=f'{plums:.0%}' if pd.notna(plums) else 'All Balls' if decisions and len(use)==0 else None,
                         vobl=actual-total(base),vobm=actual-total(bench),
                         wobl=total(win(a,b) for a,b in zip(g.actual_points,base)),
                         wobm=total(win(a,b) for a,b in zip(g.actual_points,bench)),
                         all_studs=int(roster.is_stud.sum()) if known else NAN,
                         studs_benched=int((roster.is_stud & ~roster.is_starting).sum()) if known else NAN,
                         all_duds=int(roster.is_dud.sum()) if known else NAN,
                         duds_started=int((roster.is_dud & roster.is_starting).sum()) if known else NAN))
    return pd.DataFrame(rows)


def payload(processor, table):
    return section(table,'Exact legal optimal lineups and projection-optimal decisions; IR/NA players excluded from optimization. VOBM/WOBM compare with the optimal free-agent lineup. Missing eligible-player scores make optimization unavailable.')
