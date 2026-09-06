"""Seeded Monte Carlo for a league, ranked by wins then points for, with optional divisions."""
import numpy as np
import pandas as pd
from .common import NAN, total, section


def build(processor):
    teams=processor.teams.team_id.tolist(); n=len(teams)
    blank=pd.DataFrame([dict(team_id=t,make_playoffs=NAN,division=NAN,wildcard=NAN,bye=NAN,last_place=NAN) for t in teams])
    settings=processor.bronze_settings
    def setting(name):
        if name in settings and settings[name].notna().any(): return int(float(settings[name].dropna().iloc[0]))
        return None
    count=processor.playoff_teams if processor.playoff_teams is not None else setting('num_playoff_teams')
    byes=processor.playoff_byes if processor.playoff_byes is not None else setting('num_playoff_byes')
    start=setting('playoff_start_week')
    if count is None or byes is None or start is None:
        blank.attrs['unavailable_reason']='Playoff qualifiers/bye counts are not archived. Supply playoff_teams and playoff_byes for a single-table league.'
        return blank
    if not (1<=count<=n and 0<=byes<=count): raise ValueError('Invalid playoff_teams/playoff_byes')
    divisions=processor.divisions
    if divisions and set(divisions)!=set(teams):
        raise ValueError('divisions must map every team_id exactly once')
    if len(set(divisions.values()))>count:
        raise ValueError('There are more division winners than playoff places')
    games=processor.silver_team_week.query('week < @start')
    if games.actual_points.isna().any() or games.win.isna().any() or games.groupby('team_id').size().min()<2:
        blank.attrs['unavailable_reason']='At least two complete scored games per team are required.'
        return blank
    future=processor.silver_schedule.query('week > @processor.current_week and week < @start')
    # Require every remaining team-week and reciprocal pair before simulating.
    expected=n*max(0,start-1-processor.current_week)
    mapping={(r.team_id,r.week):r.opponent_id for r in future.itertuples()}
    if len(future)!=expected or any(mapping.get((opp,w))!=team for (team,w),opp in mapping.items()):
        blank.attrs['unavailable_reason']='The remaining regular-season schedule is incomplete.'
        return blank
    stats=games.groupby('team_id').actual_points.agg(['mean','std']).reindex(teams)
    count_sim=processor.simulation_count
    rng=np.random.default_rng(processor.random_seed)
    wins=np.tile(games.groupby('team_id').win.sum().reindex(teams).to_numpy(),(count_sim,1))
    points=np.tile(games.groupby('team_id').actual_points.sum().reindex(teams).to_numpy(),(count_sim,1))
    idx={t:i for i,t in enumerate(teams)}
    for week,g in future.groupby('week'):
        scores=rng.normal(stats['mean'].to_numpy(),stats['std'].to_numpy(),size=(count_sim,n))
        points+=scores
        for r in g.itertuples():
            i,j=idx[r.team_id],idx[r.opponent_id]
            wins[:,i]+=(scores[:,i]>scores[:,j])+.5*(scores[:,i]==scores[:,j])
    # Random tertiary tie-break prevents persistent bias toward a team ID.
    order=np.lexsort((rng.random((count_sim,n)),-points,-wins),axis=1)
    ranks=np.argsort(order,axis=1)
    standings_ranks=ranks.copy()
    division_winner=np.zeros((count_sim,n),dtype=bool)
    if divisions:
        winners=[]
        for name in sorted(set(divisions.values())):
            members=np.array([idx[t] for t in teams if divisions[t]==name])
            winners.append(members[np.argmin(ranks[:,members],axis=1)])
        winners=np.stack(winners,axis=1)
        division_winner[np.arange(count_sim)[:,None],winners]=True
        # Division winners receive the first seeds, in standings order.
        ordered_winners=np.take_along_axis(winners,np.argsort(np.take_along_axis(ranks,winners,axis=1),axis=1),axis=1)
        other_seeds=order[~np.take_along_axis(division_winner,order,axis=1)].reshape(count_sim,n-len(winners[0]))
        seeds=np.concatenate([ordered_winners,other_seeds],axis=1)
        ranks=np.argsort(seeds,axis=1)
    out=pd.DataFrame({'team_id':teams,'make_playoffs':(ranks<count).mean(axis=0),
                      'division':division_winner.mean(axis=0),'wildcard':((ranks<count)&~division_winner).mean(axis=0),
                      'bye':(ranks<byes).mean(axis=0),'last_place':(standings_ranks==n-1).mean(axis=0)})
    return out


def payload(processor, table):
    reason=table.attrs.get('unavailable_reason')
    return section(table,reason or ('Normal-score Monte Carlo through the regular season. Wins, then points for, then random tie-break. Configured division winners qualify and receive the first seeds; remaining places are wildcards.' if processor.divisions else 'Normal-score Monte Carlo through the regular season. Single-table standings; wins, then points for, then random tie-break. No divisions configured.'),
                   simulation_count=0 if reason else processor.simulation_count,
                   unavailable_reason=reason)
