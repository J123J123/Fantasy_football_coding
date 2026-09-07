"""Exact position-constrained assignment, including flex and multi-position players."""
import ast
import re
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from .processor import NON_STARTERS
from .common import NAN, total


def eligibility(row):
    if isinstance(row.get("_eligibility"), set): return row["_eligibility"]
    if isinstance(row.get('eligible_positions'), (list, tuple, set)):
        return set(row['eligible_positions']) - NON_STARTERS
    positions=set()
    def collect(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='position': positions.add(str(v))
                else: collect(v)
        elif isinstance(value,list):
            for v in value: collect(v)
    for key,value in row.items():
        if 'eligible_positions_to_add' in key:
            continue
        if key.endswith('eligible_positions') and isinstance(value,str):
            try: collect(ast.literal_eval(value))
            except (ValueError,SyntaxError): positions.update(value.replace(',','/').split('/'))
        elif ('eligible_positions' in key and key.endswith('_position')) and pd.notna(value): positions.add(str(value))
    for key in ('primary_position','position','display_position'):
        if pd.notna(row.get(key)): positions.update(str(row[key]).split(','))
    return positions-NON_STARTERS


def eligible(positions,slot):
    if slot in positions: return True
    flex={'W/R':{'WR','RB'},'W/T':{'WR','TE'},'W/R/T':{'WR','RB','TE'},
          'Q/W/R/T':{'QB','WR','RB','TE'},'FLEX':{'WR','RB','TE'},'SUPER_FLEX':{'QB','WR','RB','TE'}}
    return bool(positions & flex.get(slot,set()))


def optimize(players, slots, metric='actual_points'):
    """Return player index per slot, or None when a complete lineup is unknown."""
    if not slots or len(players)<len(slots) or players[metric].isna().all(): return None
    positions=players['_eligibility'].tolist() if '_eligibility' in players else [eligibility(row) for _,row in players.iterrows()]
    fits=np.array([[eligible(pos,s[0]) for pos in positions] for s in slots])
    usable=fits.any(axis=0)
    if players.loc[usable,metric].isna().any(): return None
    scores=players[metric].fillna(0).to_numpy(float)
    costs=np.where(fits,-scores[None,:],1e12)
    ri,ci=linear_sum_assignment(costs)
    if len(ri)!=len(slots) or (costs[ri,ci]>=1e12).any(): return None
    return players.index.to_numpy()[ci].tolist()


def roster_pool(players, archived):
    """Playable roster rows and whether any archived playable player is missing."""
    pool = players[~players.roster_slot.isin(NON_STARTERS - {'BN'})]
    archived = archived[~archived.roster_slot.isin(NON_STARTERS - {'BN'})]
    return pool, not set(archived.player_id).issubset(set(pool.player_id))


def add_player_lineup_columns(players, slots, roster):
    """Weekly actual-score ranks and legal optimal flags for each team/FA pool."""
    out = players.copy()
    playable = ~out.roster_slot.isin(NON_STARTERS - {'BN'})
    positions = out.eligible_positions.map(set)
    for slot in dict.fromkeys(slot for slot, _ in slots):
        column = 'rank_' + re.sub(r'[^a-z0-9]+', '_', slot.lower()).strip('_')
        candidates = out[playable & positions.map(lambda pos: eligible(pos, slot))]
        ranks = candidates.groupby(['week', 'team_id'], dropna=False).actual_points.rank(
            ascending=False, method='min')
        out[column] = ranks.reindex(out.index).astype('Int64')
    out['is_optimal'] = pd.Series(False, index=out.index, dtype='boolean')
    for (week, team), group in out.groupby(['week', 'team_id'], dropna=False):
        archived = roster[roster.week.eq(week) & roster.team_id.eq(team)] if pd.notna(team) else roster.iloc[:0]
        pool, missing = roster_pool(group, archived)
        selected = None if missing else optimize(pool, slots)
        if selected is None:
            out.loc[pool.index, 'is_optimal'] = pd.NA
        else:
            out.loc[selected, 'is_optimal'] = True
    return out


def build_lineups(processor):
    rows=[]; slots=processor.lineup_slots
    for (team,week),g in processor.silver_player.dropna(subset=['team_id']).groupby(['team_id','week']):
        archived = processor.bronze_team_data
        archived = archived[archived.team_id.eq(team) & archived.week.eq(week)]
        g, missing_players = roster_pool(g, archived)
        actual=None if missing_players else optimize(g,slots)
        projected=None if missing_players else optimize(g,slots,'projected_points')
        starters=g[g.is_starting]
        projected_total=total(g.loc[projected,'projected_points']) if projected is not None else NAN
        using=(abs(total(starters.projected_points)-projected_total)<1e-8) if projected is not None and len(starters)==len(slots) and starters.projected_points.notna().all() else None
        rows.append(dict(team_id=team,week=week,optimal_points=total(g.loc[actual,'actual_points']) if actual is not None else NAN,
                         optimal_player_indices=actual,projected_player_indices=projected,
                         yahoo_actual_points=total(g.loc[projected,'actual_points']) if projected is not None else NAN,
                         using_yahoo=using))
    return pd.DataFrame(rows,columns=['team_id','week','optimal_points','optimal_player_indices','projected_player_indices','yahoo_actual_points','using_yahoo'])
