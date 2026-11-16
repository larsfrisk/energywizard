"""Personal native standby and scoped ownership without weakening hold/idle."""
import pytest
import shadow
import battery_commands
import battery_control
from battery_follow import mismatch
from house_config import build_battery_driver, battery_settings
from drivers.battery_ferroamp import FerroampBatteryDriver
from drivers.ferroamp_modbus import float_words
from test_ferroamp_drivers import hub, MODBUS
from test_battery_control import BASE, STYR


def device(**changes):
    return FerroampBatteryDriver(**{**dict(modbus=MODBUS,control_enabled=True,default_mode_verified=True,
        live_control_confirmed=True,exclusive_owner_confirmed=True,standby_reference_w=10,standby_verified=True), **changes})


def test_scoped_battery_commands_work_in_shadow_without_advertising_false_hold(hub, monkeypatch):
    monkeypatch.setattr(shadow,'active',lambda:True)
    d=device()
    assert d.supported_intents() == {'auto','charge','discharge','standby'}
    assert not d.apply_intent('hold') and not d.apply_intent('idle')
    assert d.apply_intent('standby')
    assert hub.writes == [(6064,float_words(.01)),(6000,1)]
    assert d.command_reference_verified and shadow.active()
    assert d.apply_intent('auto') and hub.writes[-1] == (6000,0)


@pytest.mark.parametrize('changes',[{'live_control_confirmed':False},{'exclusive_owner_confirmed':False}])
def test_scope_requires_explicit_ownership_and_live_confirmation(hub, monkeypatch, changes):
    monkeypatch.setattr(shadow,'active',lambda:True)
    monkeypatch.setattr(shadow,'record',lambda *args:None)
    assert device(**changes).apply_intent('charge',1000)
    assert hub.writes == [] and hub.reads == []


def test_standby_requires_explicit_firmware_verification(hub):
    assert 'standby' not in device(standby_verified=False).supported_intents()
    assert not device(standby_verified=False).apply_intent('standby')
    assert hub.writes == []
    assert not device().apply_intent('standby', 1000)
    assert hub.writes == []


@pytest.mark.parametrize('watts',[0,-1,True,float('nan'),float('inf'),51])
def test_invalid_standby_reference_cannot_enable_control(watts):
    with pytest.raises(ValueError):device(standby_reference_w=watts)


def test_standby_fresh_soc_reserve_and_release_checks(hub):
    hub.inputs[6016]=float_words(20)
    d=device(reserve_soc=20)
    assert not d.apply_intent('standby') and hub.writes == []
    assert d.apply_intent('auto')  # Release does not need a discharge authorization.
    assert hub.writes == [(6000,0)]


def test_policy_maps_only_explicitly_opted_in_hold_to_distinct_standby(hub):
    d=device()
    state={**BASE,'ev_charging_grid':True}
    cfg={**STYR,'standby_for_hold':True,'standby_reference_w':10}
    result=battery_control.decide(state,cfg,d.supported_intents())
    assert result['intent']=='standby' and result['power_w']==10
    assert 'stoppar även solladdning' in result['reason']
    assert battery_control.decide(state,STYR,d.supported_intents())['intent']=='auto'
    assert battery_control.decide({**state,'soc':20},cfg,d.supported_intents())['intent']=='auto'
    assert battery_control.decide(state,cfg,{'auto','hold','standby'})['intent']=='hold'


def test_tracker_records_actual_scoped_command_and_dated_standby_delivery(hub,monkeypatch):
    monkeypatch.setattr(shadow,'active',lambda:True)
    events=[];tracker=battery_commands.Tracker(events.append)
    assert battery_commands.apply(tracker,device(),'standby',10)
    assert tracker.current['accepted'] is True
    assert events[-1]['state']=='reference_verified'
    stamp=tracker.current['sent_at']+1
    tracker.observe(tracker.current['command_id'],{'power_w':-10,'power_sample_at':stamp},stamp+1)
    assert events[-1]['state']=='physically_applied'
    assert mismatch('standby',10,2000,50,20) is not None
    assert mismatch('standby',10,-10,50,20) is None


def test_builder_and_normalized_policy_keep_all_confirmations_explicit(hub):
    cfg={'battery':{'enabled':True,'driver':'ferroamp_modbus','control':'styr','modbus':MODBUS,
        'default_mode_verified':True,'exclusive_owner_confirmed':True,'live_control_confirmed':True,
        'standby_verified':True,'standby_reference_w':10,'standby_for_hold':True}}
    driver=build_battery_driver(cfg)
    assert driver._live_in_shadow is True and 'standby' in driver.supported_intents()
    assert battery_settings(cfg)['standby_for_hold'] is True
    cfg['battery']['control']='samarbete'
    assert build_battery_driver(cfg)._live_in_shadow is False
    assert build_battery_driver(cfg).supported_intents() == set()


def test_optimizer_can_preserve_energy_for_expensive_hours_with_real_standby_cost():
    from battery_plan import optimize
    from test_battery_plan import _slots
    result=optimize(_slots([.1]*8+[3]*8),5,10,2,10,3,3,
        allowed={'auto','standby','charge','discharge'},standby_kw=.01,switch_cost=0,cycle_cost=.1)
    standby=[r for r in result['rows'] if r['action']=='standby']
    assert standby and all(r['battery_kw']==-.01 for r in standby)
    assert all(abs(r['grid_kw']-(1-.01))<1e-9 for r in standby)
    assert any(r['action']=='discharge' for r in result['rows'][8:])
    assert all(r['action'] not in {'hold','idle'} for r in result['rows'])


def test_standby_is_not_invented_at_reserve_or_clipped_to_avoid_export():
    from battery_plan import optimize
    from test_battery_plan import _slots
    at_reserve=optimize(_slots([1]*4),2,10,2,10,3,3,allowed={'auto','standby'})
    assert all(r['action']!='standby' for r in at_reserve['rows'])
    exporting=optimize(_slots([1]*4,load=0,solar=[1]*4),5,10,2,10,3,3,
        allowed={'auto','standby'},allow_export=False)
    assert all(r['action']!='standby' for r in exporting['rows'])
    cfg={**STYR,'standby_for_hold':True,'standby_reference_w':10,'allow_export':False}
    result=battery_control.decide({**BASE,'ev_charging_grid':True,'avg_net_w':0},cfg,device().supported_intents())
    assert result['intent']=='auto'


def test_standby_plan_capture_round_trips_with_explicit_reference():
    import battery_plan
    import plan_snapshot
    from test_plan_snapshot import example
    slots, params, _, now=example()
    params.update(allowed={'auto','standby','charge','discharge'},standby_kw=.02)
    result=battery_plan.optimize(slots,**params)
    capture=plan_snapshot.build(slots,params,result,now)
    assert capture['inputs']['params']['standby_kw']==.02
    assert plan_snapshot.replay(capture)['matches']
    slots, params, result, now=example()
    assert 'standby_kw' not in plan_snapshot.build(slots,params,result,now)['inputs']['params']


def test_ambiguous_power_write_is_reconciled_without_replaying(hub):
    from pymodbus.exceptions import ModbusException
    d=device()
    original=hub.write_registers
    def uncertain(address, values, *, device_id):
        result=original(address,values,device_id=device_id)
        raise ModbusException('ambiguous')
    hub.write_registers=uncertain
    assert not d.apply_intent('charge',1000)
    assert len(hub.writes)==1
    assert not d.apply_intent('charge',1000)
    assert len(hub.writes)==1
    # An independently observed mode/reference can reconcile the single attempt.
    hub.inputs[6104]=[1]
    assert d.apply_intent('charge',1000)
    assert len(hub.writes)==1 and d.command_reference_verified


def test_ambiguous_release_does_not_replay_or_allow_new_force(hub):
    from pymodbus.exceptions import ModbusException
    d=device()
    hub.inputs[6104]=[1]
    def uncertain(address, value, *, device_id):
        hub.writes.append((address,value))
        raise ModbusException('ambiguous')
    hub.write_register=uncertain
    assert not d.apply_intent('auto')
    assert not d.apply_intent('auto')
    assert not d.apply_intent('charge',1000)
    assert hub.writes==[(6000,0)]
    hub.inputs[6104]=[0]
    assert d.apply_intent('auto') and hub.writes==[(6000,0)]
