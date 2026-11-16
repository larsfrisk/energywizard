import ast
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import battery_limits
import battery_control
from battery_plan import optimize
from drivers.battery_ferroamp import FerroampBatteryDriver
from drivers.ferroamp_modbus import float_words
from test_ferroamp_drivers import hub, MODBUS
from test_battery_control import BASE, ALL

CONFIG = {'control':'styr','reserve_soc':10,'max_soc':100,'normal_max_soc':90,
          'discharge_buffer_soc':2,'max_power_w':500}


def test_legacy_defaults_and_explicit_operating_range():
    assert battery_limits.resolve({'reserve_soc':10,'max_soc':100})['normal_max_soc']==100
    limits=battery_limits.resolve(CONFIG)
    assert limits['discharge_floor_soc']==12 and limits['max_soc']==100
    assert battery_limits.resolve(CONFIG,{'battery_normal_max_soc':85})['normal_max_soc']==85


@pytest.mark.parametrize('values',[
    {'battery_normal_max_soc':None},{'battery_normal_max_soc':True},{'battery_normal_max_soc':'90'},
    {'battery_normal_max_soc':float('nan')},{'battery_normal_max_soc':101},
    {'battery_normal_max_soc':12},{'battery_discharge_buffer_soc':-1},
    {'battery_discharge_buffer_soc':21},{'battery_normal_max_soc':11},
])
def test_invalid_settings_cannot_remove_limits(values):
    with pytest.raises(ValueError):battery_limits.resolve(CONFIG,values)


def test_normal_ceiling_applies_to_negative_prices_topup_and_solar_hold():
    for extra in ({'price':-1},{'topup_target':100},{'planned_action':'charge'},
                  {'planned_action':'auto','avg_net_w':-1000}):
        result=battery_control.decide({**BASE,'soc':95,**extra},CONFIG,ALL)
        assert result['intent']!='charge'
        if extra.get('planned_action')=='auto':assert result['intent']=='idle'
    result=battery_control.decide({**BASE,'soc':85,'price':-1},CONFIG,ALL)
    assert result['intent']=='charge'


def test_scheduled_maintenance_and_discharge_remain_available_above_daily_ceiling():
    result=battery_control.decide({**BASE,'soc':95,'planned_action':'charge','balance_target_soc':100},CONFIG,ALL)
    assert result['intent']=='charge' and result['rule']=='balance'
    result=battery_control.decide({**BASE,'soc':95,'planned_action':'discharge'},CONFIG,ALL)
    assert result['intent']=='discharge'


def test_reserve_buffer_stops_forced_discharge_but_allows_verified_standby():
    cfg={**CONFIG,'standby_for_hold':True,'standby_reference_w':10}
    result=battery_control.decide({**BASE,'soc':11,'planned_action':'discharge'},cfg,{'auto','charge','discharge','standby'})
    assert result['intent']=='standby' and result['power_w']==10
    result=battery_control.decide({**BASE,'soc':10,'planned_action':'discharge'},cfg,{'auto','charge','discharge','standby'})
    assert result['intent']!='discharge' and result['intent']!='standby'


def test_reserve_limit_change_is_not_delayed_by_command_dwell():
    now=datetime.now(timezone.utc)
    decision=battery_control.decide({**BASE,'soc':11,'planned_action':'discharge'},CONFIG,ALL)
    assert decision['rule']=='reserve'
    assert battery_control.should_apply(decision,{'intent':'discharge','power_w':500,'rule':'plan'},
                                        now-timedelta(seconds=10),now)


def test_native_fresh_soc_enforces_both_limits_and_qualified_maintenance(hub):
    d=FerroampBatteryDriver(modbus=MODBUS,control_enabled=True,default_mode_verified=True,
        normal_max_soc=90,reserve_soc=10,discharge_buffer_soc=2,max_soc=100,
        standby_verified=True,standby_reference_w=10,maintenance_soc=100)
    hub.inputs[6016]=float_words(95)
    assert not d.apply_intent('charge',500) and hub.writes==[]
    d.set_balancing(True)
    assert d.apply_intent('charge',500)
    d.set_balancing(False);hub.writes.clear();hub.inputs[6016]=float_words(11)
    assert not d.apply_intent('discharge',500) and hub.writes==[]
    assert d.apply_intent('standby')


@pytest.mark.parametrize('margin',[True,None,'2',float('inf'),-1,21])
def test_native_reserve_margin_rejects_invalid_values(margin):
    with pytest.raises(ValueError):
        FerroampBatteryDriver(discharge_buffer_soc=margin)


def test_planner_keeps_existing_energy_above_ceiling_and_returns_to_daily_limit():
    slots=[{'t':i,'buy':-1,'sell':0,'load_kw':0,'solar_kw':0,'ev_kw':0} for i in range(12)]
    result=optimize(slots,9.5,10,1.2,9,3,3,allowed={'charge','hold','discharge'},eff=1,switch_cost=0)
    first=result['rows'][0]
    assert first['soc_kwh']==pytest.approx(9.5+first['battery_kw']*.25,abs=.06)
    assert all(r['soc_kwh']<=9.06 for r in result['rows'] if r['battery_kw']>0)


def test_actual_settings_endpoint_rejects_invalid_or_unauthorized_changes(monkeypatch):
    from starlette.responses import JSONResponse
    import ew_settings
    import house_config
    root=Path(__file__).resolve().parents[1]
    node=next(n for n in ast.parse((root/'webdashboard/app.py').read_text()).body
              if isinstance(n,ast.AsyncFunctionDef) and n.name=='api_battery_plan_settings_save')
    node.decorator_list=[]
    role=['owner'];writes=[]
    monkeypatch.setattr(ew_settings,'load',lambda:{})
    monkeypatch.setattr(ew_settings,'update',lambda **kw:writes.append(kw))
    monkeypatch.setattr(house_config,'load_house_config',lambda path:{'battery':{'enabled':True,**CONFIG}})
    scope={'Request':object,'JSONResponse':JSONResponse,'AUTH':SimpleNamespace(session=lambda r:(role[0],'user')),
           'ew_settings':ew_settings,'house_config':house_config,'HOUSE_CONFIG_FILE':'synthetic'}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),scope)
    class Request:
        def __init__(self,body):self.body=body
        async def json(self):return self.body
    call=lambda body:asyncio.run(scope[node.name](Request(body)))
    assert call({'normal_max_soc':85})['normal_max_soc']==85
    assert writes==[{'battery_normal_max_soc':85,'battery_discharge_buffer_soc':2}]
    assert call({'normal_max_soc':101}).status_code==400
    assert call({'normal_max_soc':True}).status_code==400
    role[0]='family'
    assert call({'normal_max_soc':80}).status_code==403
    assert len(writes)==1
