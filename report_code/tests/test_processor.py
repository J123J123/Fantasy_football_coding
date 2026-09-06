import json
import re
from pathlib import Path

import pandas as pd
import pytest

from report_code import ReportProcessor
from report_code.lineups import optimize


@pytest.fixture
def archive(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({'current_week':2,'last_collected_week':3,
        'start_week':1,'season':2025,'league_key':'l','league_name':'Test </script><script>bad()</script>'}))
    def write(name, week, rows):
        d=tmp_path/name; d.mkdir(exist_ok=True)
        pd.DataFrame(rows).to_csv(d/f'{name}_week_{week}.csv.gz',index=False)
    for week in (1,2,3):
        players=[]; projections=[]; rosters=[]
        for pid,team,pos,slot,score in [('1','1','RB','RB',10),('2','1','WR','W/R/T',8),
                ('3','1','RB','BN',20),('4','2','RB','RB',12),('5','2','WR','W/R/T',14),
                ('6','2','WR','BN',3),('7',None,'RB',None,7),('8',None,'WR',None,5)]:
            players.append(dict(player_id=pid,week=week,primary_position=pos,player_name='Player '+pid,
                                fantasy_points_actual=score+week,player_points_coverage_type='week'))
            projections.append(dict(player_id=pid,week=week,projected_points=int(pid)+week))
            if team:
                rosters.append(dict(player_id=pid,week=week,team_id=team,team_name='Team '+team,
                                    roster_slot=slot,is_starting=slot!='BN'))
        write('player_data',week,players); write('projection_data',week,projections); write('team_data',week,rosters)
        write('draft',week,[dict(player_id=str(i),week=week,team_id='1' if i<4 else '2',round=i) for i in range(1,7)])
        write('league_settings',week,[dict(week=week,setting_type='league',playoff_start_week=4,num_playoff_teams=1,num_playoff_byes=0),
            dict(week=week,setting_type='roster_position',position='RB',count=1),
            dict(week=week,setting_type='roster_position',position='W/R/T',count=1)])
        write('schedule',week,[{'team_key':'l.t.1','week_1':'l.t.2','week_2':'l.t.2','week_3':'l.t.2'},
                              {'team_key':'l.t.2','week_1':'l.t.1','week_2':'l.t.1','week_3':'l.t.1'}])
    official=tmp_path/'scores.csv'
    pd.DataFrame([dict(team_id=t,week=w,official_points=s+2*w) for t,s in [('1',18),('2',26)] for w in (1,2,3)]).to_csv(official,index=False)
    return tmp_path


def test_metadata_week_snapshot_selection_and_joins(archive):
    r=ReportProcessor(archive)
    assert r.current_week==2
    assert len(r.silver_player)==16
    assert r.bronze_player.week.max()==2
    assert r.bronze_settings.week.unique().tolist()==[2]
    player=r.silver_player.query("player_id == '1'")
    assert player.projected_points.tolist()==[2,3]
    assert player.draft_round.tolist()==[1,1]
    assert ReportProcessor(archive/'metadata.json',1).bronze_draft.week.unique().tolist()==[1]


def test_reconciliation_and_missing_scores(archive):
    r=ReportProcessor(archive,official_scores_path=archive/'scores.csv')
    r.validate_reconciliation()
    assert r.silver_season_reconciliation.calculated_points.tolist()==[42,58]
    assert r.silver_reconciliation.status.eq('matched').all()
    r=ReportProcessor(archive)
    assert r.silver_reconciliation.status.eq('unverified').all()
    with pytest.raises(ValueError,match='could not be reconciled'): r.validate_reconciliation()
    r=ReportProcessor(archive,official_scores_path=archive/'scores.csv')
    r.bronze_player.loc[0,'fantasy_points_actual']=None
    assert r.silver_reconciliation.iloc[0].status=='missing_player_points_or_roster'
    assert pd.isna(r.silver_season_reconciliation.iloc[0].calculated_points)


def test_missing_player_and_duplicate_roster_are_detected(archive):
    r=ReportProcessor(archive)
    r.bronze_player.drop(index=0,inplace=True)
    assert r.silver_reconciliation.iloc[0].status=='missing_player_points_or_roster'
    r=ReportProcessor(archive)
    r.bronze_projection.loc[len(r.bronze_projection)]=r.bronze_projection.iloc[0]
    with pytest.raises(ValueError,match='duplicate join keys'): _=r.silver_player


def test_weekly_coverage_and_official_mismatch(archive):
    r=ReportProcessor(archive)
    r.bronze_player.loc[0,'player_points_coverage_type']='season'
    assert pd.isna(r.silver_player.iloc[0].actual_points)
    scores=pd.read_csv(archive/'scores.csv'); scores.loc[0,'official_points']+=1
    scores.to_csv(archive/'scores.csv',index=False)
    r=ReportProcessor(archive,official_scores_path=archive/'scores.csv')
    assert r.silver_reconciliation.iloc[0].status=='mismatch'


def test_flex_optimizer_does_not_reuse_players():
    players=pd.DataFrame([dict(primary_position='RB',actual_points=10),
                          dict(primary_position='WR',actual_points=20),
                          dict(primary_position='RB',actual_points=9)])
    selected=optimize(players,[('W/R/T',1),('RB',1)])
    assert selected==[1,0]
    future=pd.DataFrame([dict(primary_position='WR',eligible_positions_to_add_0_position='QB',actual_points=20)])
    assert optimize(future,[('QB',1)]) is None
    players.loc[2,'actual_points']=None
    assert optimize(players,[('W/R/T',1),('RB',1)]) is None


def test_gold_calculations_and_round_trip(archive,tmp_path):
    r=ReportProcessor(archive,simulation_count=100,official_scores_path=archive/'scores.csv')
    payload=r.to_dict()
    assert len(r.gold_tables)==10
    assert all(isinstance(t,pd.DataFrame) for t in r.gold_tables.values())
    assert r.gold_managerial_expertise.iloc[0].actual_points==42
    assert r.gold_managerial_expertise.iloc[0].optimal_points==66
    assert payload['freaky_friday']['schedule_swap']['matrix']['1']['1']==0
    assert payload['freaky_friday']['schedule_swap']['matrix']['1']['2']==0
    assert payload['freaky_friday']['head_to_head']['matrix']['2']['1']==2
    assert sum(payload['draft_analysis']['historical'][0]['values'].values())==42
    assert sum(payload['draft_analysis']['optimal'][0]['values'].values())==66
    assert sum(x['make_playoffs'] for x in payload['playoff_odds']['rows'])==pytest.approx(1)
    assert r.gold_bhole.iloc[0]['range']==2
    json.loads(r.to_json(),parse_constant=lambda v: pytest.fail(v))
    output=r.write_html(tmp_path/'report.html').read_text()
    embedded=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',output,re.S)[1]
    assert json.loads(embedded)['meta']['league_name']==r.metadata['league_name']
    assert '<script>bad()' not in output


def test_draft_ownership_and_repeatable_simulation(archive):
    r=ReportProcessor(archive,simulation_count=100)
    r.bronze_draft.loc[r.bronze_draft.player_id.eq('1'),'team_id']='2'
    assert r.gold_draft_analysis.iloc[0]['values']['FA']==23
    a=ReportProcessor(archive,simulation_count=100).gold_playoff_odds
    b=ReportProcessor(archive,simulation_count=100).gold_playoff_odds
    pd.testing.assert_frame_equal(a,b)


def test_missing_whole_week_never_becomes_zero(archive):
    (archive/'player_data/player_data_week_2.csv.gz').unlink()
    r=ReportProcessor(archive)
    assert r.silver_reconciliation.query('week == 2').calculated_points.isna().all()
    assert r.gold_managerial_expertise.actual_points.isna().all()
    assert r.gold_draft_analysis['values'].map(lambda d: all(pd.isna(v) for v in d.values())).all()


def test_future_only_and_bad_weeks(archive):
    with pytest.raises(ValueError): ReportProcessor(archive,0)
    with pytest.raises(ValueError): ReportProcessor(archive,1.5)
    with pytest.raises(FileNotFoundError):
        _=ReportProcessor(archive,1,data_files={'draft':archive/'draft/draft_week_3.csv.gz'}).bronze_draft


def test_wrong_projection_week_is_unavailable(archive):
    r=ReportProcessor(archive)
    r.bronze_projection['projection_week_returned']=r.bronze_projection.week
    r.bronze_projection.loc[0,'projection_week_returned']=9
    assert pd.isna(r.silver_player.iloc[0].projected_points)


def test_division_winners_and_wildcard_probabilities(archive):
    r=ReportProcessor(archive,simulation_count=100,playoff_teams=2,playoff_byes=1,
                      divisions={'1':'East','2':'West'})
    odds=r.gold_playoff_odds
    assert odds.make_playoffs.eq(1).all()
    assert odds.division.eq(1).all()
    assert odds.wildcard.eq(0).all()
    assert odds.bye.sum()==pytest.approx(1)
    assert odds.last_place.sum()==pytest.approx(1)
    r=ReportProcessor(archive,divisions={'1':'East'})
    with pytest.raises(ValueError,match='every team_id'): _=r.gold_playoff_odds


def test_team_missing_from_all_rosters_still_reconciled(archive):
    r=ReportProcessor(archive)
    r.bronze_team_data.drop(r.bronze_team_data.index[r.bronze_team_data.team_id.eq('2')],inplace=True)
    assert len(r.teams)==2
    assert r.silver_reconciliation.query("team_id == '2'").calculated_points.isna().all()


def test_boned_index_known_opponent_baselines(archive):
    r=ReportProcessor(archive)
    r.teams=pd.DataFrame({'team_id':['1','2','3','4'],'team_name':['A','B','C','D'],'manager':['A','B','C','D']})
    r.silver_team_week=pd.DataFrame([
        dict(team_id='1',week=1,actual_points=10,opponent_id='2',opponent_points=20),
        dict(team_id='2',week=1,actual_points=20,opponent_id='1',opponent_points=10),
        dict(team_id='3',week=1,actual_points=30,opponent_id='4',opponent_points=40),
        dict(team_id='4',week=1,actual_points=40,opponent_id='3',opponent_points=30),
        dict(team_id='1',week=2,actual_points=20,opponent_id='3',opponent_points=10),
        dict(team_id='3',week=2,actual_points=10,opponent_id='1',opponent_points=20),
        dict(team_id='2',week=2,actual_points=30,opponent_id='4',opponent_points=20),
        dict(team_id='4',week=2,actual_points=20,opponent_id='2',opponent_points=30)])
    assert r.gold_boned_index.query("team_id == '1'").value.iloc[0]==pytest.approx(-50)
    assert r.gold_boned_detail.query("team_id == '1'").opponent_avg.tolist()==[30,30]


def test_stud_dud_thresholds_and_bench_exclusion(archive):
    r=ReportProcessor(archive,1)
    r.bronze_player['fantasy_points_actual']=r.bronze_player.fantasy_points_actual.astype(float)
    for pid,actual,projected in [('1',20,10),('2',20,9),('3',30,10),('4',2.5,10),('5',0,9)]:
        r.bronze_player.loc[r.bronze_player.player_id.eq(pid),'fantasy_points_actual']=actual
        r.bronze_projection.loc[r.bronze_projection.player_id.eq(pid),'projected_points']=projected
    out=r.gold_studs_duds.set_index('team_id')
    assert out.loc['1','studs']==1
    assert out.loc['2','duds']==1
    assert out.loc['1','dudded_on']==1
    assert out.loc['1','s2d_diff']==2
