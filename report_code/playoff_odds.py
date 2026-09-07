"""Seeded Monte Carlo for a league, ranked by wins then points for, with optional divisions."""
import numpy as np
import pandas as pd
from .common import NAN, total, section


# Standard single-elimination brackets: qualifiers -> playoff rounds (weeks).
# Empty first-round slots become byes, e.g. 6 teams over 3 rounds: 8 - 6 = 2.
PLAYOFF_ROUNDS = {
    1: 0, 2: 1, 3: 2, 4: 2,
    5: 3, 6: 3, 7: 3, 8: 3,
    9: 4, 10: 4, 11: 4, 12: 4,
    13: 4, 14: 4, 15: 4, 16: 4,
}
STD_EXPONENTS = np.arange(1, 11) / 4
SCORE_MIN = 60.0
SCORE_MAX = 200.0


def simulation_scales(standard_deviations, simulation_count):
    """Equal-sized exponent groups; each season keeps its exponent across weeks."""
    exponents = np.repeat(STD_EXPONENTS, simulation_count // len(STD_EXPONENTS))
    return np.asarray(standard_deviations)[None, :] ** exponents[:, None]


def simulated_scores(rng, means, scales):
    return np.clip(rng.normal(means, scales), SCORE_MIN, SCORE_MAX)


def score_parameters(games, teams, current_week, blend_weeks=10):
    """Blend team and pooled team-week statistics over the configured window."""
    stats = games.groupby('team_id').actual_points.agg(['mean', 'std']).reindex(teams)
    weight = min(current_week, blend_weeks) / blend_weeks
    pooled = games.actual_points
    stats['mean'] = weight * stats['mean'] + (1 - weight) * pooled.mean()
    stats['std'] = weight * stats['std'] + (1 - weight) * pooled.std(ddof=1)
    return stats


def build(processor):
    teams=processor.teams.team_id.tolist(); n=len(teams)
    blank=pd.DataFrame([dict(team_id=t,make_playoffs=NAN,division=NAN,wildcard=NAN,bye=NAN,last_place=NAN) for t in teams])
    settings=processor.bronze_settings
    def setting(name):
        if name in settings and settings[name].notna().any(): return int(float(settings[name].dropna().iloc[0]))
        return None
    count=processor.playoff_teams if processor.playoff_teams is not None else setting('num_playoff_teams')
    byes=processor.playoff_byes
    if byes is None and count in PLAYOFF_ROUNDS:
        byes=2**PLAYOFF_ROUNDS[count]-count
    start=setting('playoff_start_week')
    if count is None or start is None:
        blank.attrs['unavailable_reason']='Playoff team count or playoff start week is missing from league settings.'
        return blank
    if byes is None:
        blank.attrs['unavailable_reason']='No standard bracket is configured for this playoff team count. Supply playoff_byes.'
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
    stats=score_parameters(games, teams, processor.current_week, processor.playoff_blend_weeks)
    count_sim=processor.simulation_count
    scales=simulation_scales(stats['std'].to_numpy(), count_sim)
    rng=np.random.default_rng(processor.random_seed)
    wins=np.tile(games.groupby('team_id').win.sum().reindex(teams).to_numpy(),(count_sim,1))
    points=np.tile(games.groupby('team_id').actual_points.sum().reindex(teams).to_numpy(),(count_sim,1))
    idx={t:i for i,t in enumerate(teams)}
    for week,g in future.groupby('week'):
        scores=simulated_scores(rng, stats['mean'].to_numpy(), scales)
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
    description = ('Normal-score Monte Carlo through the regular season. '
                   'Scoring means and sample standard deviations blend team and league-wide scores '
                   f'with team weight min(week, {processor.playoff_blend_weeks})/{processor.playoff_blend_weeks}; '
                   f'week {processor.playoff_blend_weeks} onward uses team statistics only. ')
    description += ('Standard deviation is raised to exponents 0.25 through 2.50 in steps of 0.25, '
                    f'with {processor.simulation_count // len(STD_EXPONENTS):,} seasons per exponent. '
                    'Simulated scores are capped at 60 and 200. ')
    description += ('Wins, then points for, then random tie-break. Configured division winners qualify and receive the first seeds; remaining places are wildcards.' if processor.divisions else 'Single-table standings; wins, then points for, then random tie-break. No divisions configured.')
    return section(table,reason or description,
                   simulation_count=0 if reason else processor.simulation_count,
                   standard_deviation_exponents=STD_EXPONENTS.tolist(),
                   simulations_per_exponent=0 if reason else processor.simulation_count // len(STD_EXPONENTS),
                   score_min=SCORE_MIN, score_max=SCORE_MAX,
                   history=processor.playoff_odds_history,
                   unavailable_reason=reason)
