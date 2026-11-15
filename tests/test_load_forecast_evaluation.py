from datetime import datetime,timedelta,timezone
import pytest
from load_forecast_evaluation import base_load_w,aggregate,evaluate

START=datetime(2026,10,1,tzinfo=timezone.utc)


@pytest.mark.parametrize('grid,pv,battery,loads,expected',[
    (2000,0,0,[],2000),(-1000,4000,1000,[],2000),
    (0,0,-2000,[],2000),(2000,4000,2000,[1000,500],2500),
])
def test_signed_boundary_and_explicit_excluded_loads(grid,pv,battery,loads,expected):
    assert base_load_w(grid,pv,battery,loads)==expected


@pytest.mark.parametrize('values',[(None,0,0,[]),(0,-1,0,[]),(0,0,0,[1]),(0,0,0,[-1]),(float('nan'),0,0,[])])
def test_missing_or_inconsistent_signals_are_not_zero_filled(values):
    with pytest.raises(ValueError):base_load_w(*values)


def test_aggregation_rejects_gaps_and_does_not_double_count_controlled_loads():
    ss=[dict(timestamp=START+timedelta(seconds=i),grid_w=3000,pv_w=0,battery_w=0,controlled_w=[1000])
        for i in range(0,1801,60)]
    rows,coverage=aggregate(ss)
    assert len(rows)==2 and rows[0]['kw']==2
    del ss[4:8]
    rows,coverage=aggregate(ss)
    assert len(rows)==1 and coverage['rejected_sample_intervals']==1


def history():
    return [{'t':START.timestamp()+i*900,'kw':2 if i<7*96 else 1} for i in range(8*96)]


def planner_snapshot(**changes):
    import battery_plan,plan_snapshot
    origin=START+timedelta(days=7)
    slots=[dict(t=origin+timedelta(minutes=i*15),buy=1 if i<4 else 3,sell=.1,
                load_kw=2,solar_kw=0,ev_kw=0) for i in range(8)]
    params=dict(soc0_kwh=2,capacity_kwh=5,reserve_kwh=1,max_kwh=5,
                charge_kw=2,discharge_kw=2,step_kwh=.5,**changes)
    return plan_snapshot.build(slots,params,battery_plan.optimize(slots,**params),origin)


@pytest.mark.parametrize('method',['median_blend','recent_trend'])
def test_paired_planner_uses_realized_load_but_never_as_forecast_features(method):
    from load_forecast_evaluation import evaluate_planner_snapshot
    data=history();snapshot=planner_snapshot()
    a=evaluate_planner_snapshot(data,snapshot,'UTC',candidate_method=method)
    for row in data[672:]:row['kw']=20
    b=evaluate_planner_snapshot(data,snapshot,'UTC',candidate_method=method)
    assert a['predictions']==b['predictions']
    for label in ('baseline','candidate'):
        assert a['results'][label]['actions']==b['results'][label]['actions']
        assert a['results'][label]['energy_cash_cost']!=b['results'][label]['energy_cash_cost']
        assert b['results'][label]['soc_bounds_respected']
    assert not a['adoption_ready']
    assert a['plan_id']==snapshot['plan_id']


@pytest.mark.parametrize('changes',[{'allow_export':False},{'ev_mode':'free'},
    {'balance_target_kwh':5,'balance_hold_slots':1,'balance_deadline_slots':8}])
def test_paired_planner_rejects_unmatched_simulator_policies(changes):
    from load_forecast_evaluation import evaluate_planner_snapshot
    with pytest.raises(ValueError,match='Simulator supports'):
        evaluate_planner_snapshot(history(),planner_snapshot(**changes))


def test_paired_planner_rejects_gaps_tampering_and_unaligned_origin():
    from load_forecast_evaluation import evaluate_planner_snapshot
    import hashlib,plan_snapshot
    snapshot=planner_snapshot()
    with pytest.raises(ValueError,match='Missing realized'):
        evaluate_planner_snapshot(history()[:675],snapshot)
    snapshot['plan_id']='tampered'
    with pytest.raises(ValueError,match='identity'):
        evaluate_planner_snapshot(history(),snapshot)
    snapshot=planner_snapshot()
    snapshot['made_at']=(START+timedelta(days=7,seconds=1)).isoformat()
    snapshot['plan_id']=hashlib.sha256(plan_snapshot.canonical({k:v for k,v in snapshot.items() if k!='plan_id'}).encode()).hexdigest()
    with pytest.raises(ValueError,match='quarter-boundary'):
        evaluate_planner_snapshot(history(),snapshot)


def test_causal_comparison_reports_metrics_but_never_adopts():
    r=evaluate(history(),START+timedelta(days=7))
    assert r['candidate']['mae_kw']<r['baseline']['mae_kw']
    assert not r['adoption_ready'] and r['economic_evaluation'] is None
    assert r['training_quarters']==672


@pytest.mark.parametrize('method',['median_blend','recent_trend'])
def test_target_and_future_observations_cannot_change_earlier_predictions(method):
    data=history();a=evaluate(data,START+timedelta(days=7),candidate_method=method)
    for row in data[7*96:]:row['kw']=20
    b=evaluate(data,START+timedelta(days=7),candidate_method=method)
    assert a['predictions'][0]['candidate_kw']==b['predictions'][0]['candidate_kw']
    assert a['predictions'][0]['baseline_kw']==b['predictions'][0]['baseline_kw']
    # Previous completed test observations are legitimately available to the next origin.
    assert a['predictions'][4]['candidate_kw']!=b['predictions'][4]['candidate_kw']


def test_sparse_or_duplicate_history_rejected():
    with pytest.raises(ValueError):evaluate(history()[:10],START+timedelta(days=7))
    with pytest.raises(ValueError):evaluate(history()+[history()[0]],START+timedelta(days=7))


@pytest.mark.parametrize('method',[None,'recent_trend'])
def test_offline_cli_has_no_adoption_side_effects(tmp_path,method):
    import json,subprocess,sys
    samples=[dict(timestamp=(START+timedelta(seconds=i)).isoformat(),grid_w=2000,pv_w=0,
                  battery_w=0,controlled_w=[]) for i in range(0,8*86400+1,60)]
    path=tmp_path/'samples.json';path.write_text(json.dumps(samples))
    run=subprocess.run([sys.executable,'scripts/evaluate_household_forecast.py',str(path),
                        '--split',(START+timedelta(days=7)).isoformat(),'--timezone','UTC']+
                       (['--candidate-method',method] if method else []),
                       text=True,capture_output=True)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result['evaluation_quarters']==96 and not result['adoption_ready']
    assert result['candidate_method']==(method or 'median_blend')
    assert list(tmp_path.iterdir())==[path]


def test_dst_repeated_hours_remain_distinct_physical_quarters():
    from zoneinfo import ZoneInfo
    start=datetime(2026,10,25,0,tzinfo=timezone.utc);zone=ZoneInfo('Europe/Stockholm')
    samples=[dict(timestamp=(start+timedelta(seconds=i)).astimezone(zone),grid_w=1000,
                  pv_w=0,battery_w=0) for i in range(0,7201,60)]
    rows,_=aggregate(samples)
    assert len(rows)==8 and len({r['t'] for r in rows})==8


def test_recent_trend_hand_calculation_decays_to_baseline_and_never_uses_future():
    from load_forecast_evaluation import forecasts_at_origin
    rows=history();origin=rows[672]['t']
    for row in rows[664:668]:row['kw']=1
    targets=[origin,origin+7200,origin+14400,origin+18000]
    result=forecasts_at_origin(rows,origin,targets,'UTC',candidate_method='recent_trend')
    assert [r['candidate_kw'] for r in result]==pytest.approx([2.35,2.175,2,2])
    for row in rows[672:]:row['kw']=1000
    assert forecasts_at_origin(rows,origin,targets,'UTC',candidate_method='recent_trend')==result


@pytest.mark.parametrize('level,expected',[(100,2.7),(0,1.4)])
def test_recent_trend_stays_within_declared_baseline_bounds(level,expected):
    from load_forecast_evaluation import forecasts_at_origin
    rows=history();origin=rows[672]['t']
    for row in rows[668:672]:row['kw']=level
    prediction=forecasts_at_origin(rows,origin,[origin],'UTC',candidate_method='recent_trend')[0]
    assert prediction['candidate_kw']==pytest.approx(expected)


def test_recent_trend_missing_quarter_falls_back_instead_of_using_old_samples():
    from load_forecast_evaluation import forecasts_at_origin
    rows=history();origin=rows[672]['t']
    # Keep at least 672 other completed training quarters while creating a recent gap.
    rows.insert(0,{'t':rows[0]['t']-900,'kw':2})
    rows=[r for r in rows if r['t']!=origin-1800]
    r=forecasts_at_origin(rows,origin,[origin],'UTC',candidate_method='recent_trend')[0]
    assert r['candidate_kw']==r['baseline_kw']


def test_recent_trend_dst_fold_uses_eight_physical_quarters():
    from load_forecast_evaluation import _recent_trend
    origin=datetime(2026,10,25,1,tzinfo=timezone.utc).timestamp()
    values={origin-i*900:(1 if i>4 else 2) for i in range(1,9)}
    assert _recent_trend(values,origin,origin,2)==pytest.approx((2.35,8))


def test_recent_trend_does_not_treat_partial_current_quarter_as_completed():
    from load_forecast_evaluation import _recent_trend
    edge=START.timestamp()
    values={edge-i*900:(1 if i>4 else 2) for i in range(1,9)}
    values[edge]=1000
    assert _recent_trend(values,edge+60,edge+60,2)==pytest.approx((2.35,8))


def test_default_candidate_is_exactly_the_existing_explicit_method():
    from load_forecast_evaluation import forecasts_at_origin,evaluate_planner_snapshot
    rows=history();origin=rows[672]['t'];targets=[origin,origin+900]
    assert forecasts_at_origin(rows,origin,targets)==forecasts_at_origin(rows,origin,targets,candidate_method='median_blend')
    assert evaluate(rows,START+timedelta(days=7))==evaluate(rows,START+timedelta(days=7),candidate_method='median_blend')
    assert evaluate_planner_snapshot(rows,planner_snapshot())==evaluate_planner_snapshot(rows,planner_snapshot(),candidate_method='median_blend')
    with pytest.raises(ValueError):forecasts_at_origin(rows,origin,targets,candidate_method='unknown')
