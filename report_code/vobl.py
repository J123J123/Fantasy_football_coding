"""Baseline ranks scale with league size and repeated roster slots."""
import pandas as pd
from .lineups import eligibility, eligible
from .common import NAN, total
from .processor import records


def weekly(processor):
    if hasattr(processor, '_weekly_baseline'): return processor._weekly_baseline
    rows=[]; n=len(processor.teams); slots=processor.lineup_slots
    for week,players in processor.silver_player.groupby('week'):
        positions=players['eligible_positions'].map(set).to_dict()
        baselines={}; consumed=set()
        # Allocate positional demand before flex demand, consuming each player once.
        ordered=sorted(slots,key=lambda s: ('/' in s[0] or 'FLEX' in s[0],s[0],s[1]))
        for slot,number in ordered:
            pool=players.loc[[i for i in players.index if i not in consumed and eligible(positions[i],slot)]]
            label=f'{slot}{number}'
            if len(pool)<n or pool.actual_points.isna().any(): baselines[label]=NAN
            else:
                best=pool.sort_values('actual_points',ascending=False).head(n)
                baselines[label]=best.actual_points.iloc[-1]; consumed.update(best.index)
        for team in processor.teams.team_id:
            starters=players[players.team_id.eq(team) & players.is_starting]
            for slot,number in slots:
                candidates=starters[starters.roster_slot.eq(slot)].sort_values('actual_points',ascending=False)
                score=candidates.actual_points.iloc[number-1] if len(candidates)>=number else NAN
                base=baselines[f'{slot}{number}']
                rows.append(dict(team_id=team,week=int(week),position=f'{slot}{number}',actual_points=score,baseline_points=base,value=score-base))
    processor._weekly_baseline = pd.DataFrame(rows)
    return processor._weekly_baseline


def build(processor):
    rows=[]
    frame=weekly(processor)
    for team in processor.teams.team_id:
        g=frame[frame.team_id.eq(team)]
        values={p:total(s.value) if s.week.nunique()==processor.current_week-int(processor.metadata.get('start_week',1))+1 else NAN
                for p,s in g.groupby('position')}
        rows.append(dict(team_id=team,total=total(values.values()),values=values))
    return pd.DataFrame(rows)


def payload(processor, table):
    return {'description':'Value above the last player needed to fill each slot league-wide: Nth QB1, 2Nth RB2, etc. Flex uses the remaining eligible pool. Repeated actual slots are ordered by points.',
            'positions':[f'{s}{n}' for s,n in processor.lineup_slots], 'rows':records(table)}
