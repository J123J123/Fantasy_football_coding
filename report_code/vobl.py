"""Baseline ranks scale with league size and repeated roster slots."""
import pandas as pd
from .lineups import eligible, optimize
from .common import NAN, total
from .processor import records


def weekly(processor):
    if hasattr(processor, '_weekly_baseline'): return processor._weekly_baseline
    rows=[]; n=len(processor.teams); slots=processor.lineup_slots
    for week,players in processor.silver_player.groupby('week'):
        positions=players['eligible_positions'].map(set).to_dict()
        baselines={}; representatives={}; consumed=set()
        # Allocate positional demand before flex demand, consuming each player once.
        ordered=sorted(slots,key=lambda s: ('/' in s[0] or 'FLEX' in s[0],s[0],s[1]))
        for slot,number in ordered:
            pool=players.loc[[i for i in players.index if i not in consumed and eligible(positions[i],slot)]]
            label=f'{slot}{number}'
            if len(pool)<n or pool.actual_points.isna().any(): baselines[label]=NAN
            else:
                best=pool.sort_values(['actual_points', 'player_id'],ascending=[False, True],kind='stable').head(n)
                baselines[label]=best.actual_points.iloc[-1]; consumed.update(best.index)
                representatives[label]=best.iloc[-1]
        free=players[players.team_id.isna()]
        selected=optimize(free, slots)
        market={f'{slot}{number}':free.loc[index] for (slot,number),index in zip(slots,selected)} if selected is not None else {}
        for team in processor.teams.team_id:
            starters=players[players.team_id.eq(team) & players.is_starting]
            for slot,number in slots:
                candidates=starters[starters.roster_slot.eq(slot)].sort_values('actual_points',ascending=False)
                score=candidates.actual_points.iloc[number-1] if len(candidates)>=number else NAN
                base=baselines[f'{slot}{number}']
                label=f'{slot}{number}'
                bl=representatives.get(label)
                bm=market.get(label)
                market_points=bm.actual_points if bm is not None else NAN
                rows.append(dict(team_id=team,week=int(week),position=label,actual_points=score,
                                 baseline_points=base,value=score-base,market_points=market_points,market_value=score-market_points,
                                 baseline_player_id=bl.player_id if bl is not None else None,
                                 baseline_player_name=bl.player_name if bl is not None else None,
                                 market_player_id=bm.player_id if bm is not None else None,
                                 market_player_name=bm.player_name if bm is not None else None))
    processor._weekly_baseline = pd.DataFrame(rows)
    return processor._weekly_baseline


def build(processor):
    rows=[]
    frame=weekly(processor)
    for team in processor.teams.team_id:
        g=frame[frame.team_id.eq(team)]
        values={p:total(s.value) if s.week.nunique()==processor.current_week-int(processor.metadata.get('start_week',1))+1 else NAN
                for p,s in g.groupby('position')}
        market_values={p:total(s.market_value) if s.week.nunique()==processor.current_week-int(processor.metadata.get('start_week',1))+1 else NAN
                       for p,s in g.groupby('position')}
        rows.append(dict(team_id=team,total=total(values.values()),values=values,
                         market_total=total(market_values.values()),market_values=market_values))
    return pd.DataFrame(rows)


DESCRIPTION = ('VOBL (Value Over Baseline League) is starter points minus the league-wide replacement baseline for each lineup slot. '
               'With N teams, each slot consumes the top N remaining eligible players and uses the Nth player as its baseline; '
               'repeated positions are allocated before flex, which uses the remaining pool. '
               'VOBM (Value Over Baseline Market) is starter points minus the best legal lineup of that week’s unrostered free agents, '
               'selected using actual points. Each market player is used once. '
               'Values sum across report weeks; positive means above the comparison and negative means below. '
               'Repeated starter slots are ordered by points. The weekly chart identifies each comparison player and their fantasy points. '
               'Missing scores or an incomplete comparison lineup are shown as unavailable.')


def payload(processor, table):
    frame=weekly(processor)
    comparisons=frame.drop_duplicates(['week','position'])
    columns=['week','position','baseline_points','baseline_player_id','baseline_player_name',
             'market_points','market_player_id','market_player_name']
    return {'description':DESCRIPTION,
            'positions':[f'{s}{n}' for s,n in processor.lineup_slots], 'rows':records(table),
            'weekly_baselines':records(comparisons[columns])}
