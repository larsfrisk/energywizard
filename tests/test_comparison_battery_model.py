"""Explicit simulation assumptions never become controller settings."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import battery_shadow as B
import battery_learning

MODEL = dict(capacity_kwh=12, reserve_soc=10, max_soc=90, charge_kw=7,
             discharge_kw=6, charge_efficiency=.9, discharge_efficiency=1)
NOW = datetime(2026,11,15,tzinfo=timezone.utc)


def event():
    return dict(now=NOW, settings=dict(control='samarbete',plan=True,capacity_kwh=10,
                max_charge_w=1000,max_discharge_w=2000), state={'soc_pct':50},
                allowed=('auto','charge'),profile={},battery_model=MODEL)


def test_model_is_frozen_and_default_absence_preserves_event(monkeypatch):
    monkeypatch.setattr(B.threading.Thread,'start',lambda self:None)
    model=deepcopy(MODEL);supplied=event();original=deepcopy(supplied)
    monitor=B.Monitor()
    assert monitor.submit({'enabled':True,'allowed_intents':['auto'],'battery_model':model},
                          supplied['settings'],supplied['state'],{},now=NOW,shadow=True)
    model['capacity_kwh']=99
    queued=monitor._queue.get_nowait()
    assert queued['battery_model']==MODEL and supplied==original
    assert B._with_battery_model({'settings':{}})=={'settings':{}}


@pytest.mark.parametrize('change', [dict(capacity_kwh=0),dict(reserve_soc=-1),
    dict(max_soc=101),dict(reserve_soc=90),dict(charge_kw=0),dict(discharge_kw=-1),
    dict(charge_efficiency=0),dict(discharge_efficiency=1.1),dict(capacity_kwh=True),
    dict(charge_kw=float('inf')),dict(reserve_soc=float('nan')),dict(token='private')])
def test_invalid_model_rejected_without_starting_worker(change):
    supplied=event();monitor=B.Monitor()
    assert not monitor.submit({'enabled':True,'allowed_intents':['auto'],'battery_model':MODEL|change},
                              supplied['settings'],supplied['state'],{},now=NOW,shadow=True)
    assert monitor._thread is None and monitor._queue.empty()


def test_incomplete_model_is_rejected():
    with pytest.raises(ValueError): B._battery_model({'capacity_kwh':12})


@pytest.mark.parametrize('learn',[False,True])
def test_explicit_model_wins_after_learning_without_mutating_controller_settings(monkeypatch,learn):
    monkeypatch.setattr(B,'_eligible',lambda e:True)
    supplied=event()|{'learn_from_history':learn};original=deepcopy(supplied)
    evaluator=B.Evaluator(lambda *args:{'use':{'capacity_kwh':15,'charge_kw':2,
                         'discharge_kw':3,'solar_factor':{1:.8}}},lambda e:e)
    result=evaluator.process(supplied)
    assert supplied==original
    assert result['settings']['capacity_kwh']==12
    assert battery_learning.planning_kw(result['settings'],'charge')==7
    assert battery_learning.planning_kw(result['settings'],'discharge')==6
    assert result['state']==supplied['state']
    if learn: assert result['settings']['solar_factor']=={1:.8}
    assert result['settings']['comparison_battery_model'] is True


def test_explicit_model_has_no_authority_when_shadow_or_origin_guard_rejects(monkeypatch):
    monkeypatch.setattr(B,'_eligible',lambda e:False)
    def forbidden(*args):raise AssertionError('No planning or learning')
    assert B.Evaluator(forbidden,forbidden).process(event()) is None


def test_active_plan_rejects_model_before_database_access():
    import battery_plan
    with pytest.raises(ValueError,match='cannot feed active'):
        battery_plan.plan_from_db(None,NOW,50,{'comparison_battery_model':True},{},{'auto'})
