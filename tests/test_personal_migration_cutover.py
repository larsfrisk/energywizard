"""Combined local hot-water cutover contract; synthetic native transport only."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

import shadow
import house_config
from drivers.heatpump_generic import GenericClimateHeatPumpDriver
from drivers.heatpump_nibe_local import NibeHotWaterOnlyDriver
from hot_water_runtime import Runtime, selected
from test_heatpump_nibe_local import heater, boost_binding, point, PRODUCT, HOLDING
from test_hot_water_runtime import house, run, prices, NOW


def setup(tmp_path, heater, **changes):
    cfg = house()
    hp = cfg['heat_pump']
    hp['driver'], hp['control_enabled'] = 'generic_climate', False
    hp['entities'] = {'climate': 'climate.original_room'}
    hw = hp['hot_water_control']
    hw.update(driver='nibe_local', live_control_confirmed=True, priority_boosts=True,
              connection={'expected_product': PRODUCT},
              points={'hot_water_boost': boost_binding(),
                      'water_temp': {'variable_id':11,'register':8,'unit':'°C'},
                      'hot_water_mode': {'variable_id':3697,'register':56,'register_type':HOLDING,
                                         'unit':'','required_value':0}})
    hw.update(changes)
    heater.points['48001'] = point(48001,450,0,divisor=1,unit='',writable=True)
    heater.points['3697'] = point(3697,56,0,divisor=1,unit='',writable=True)
    primary = house_config.build_heat_pump_driver(cfg)
    local = house_config.build_hot_water_driver(cfg, primary)
    runtime = Runtime(tmp_path/'control.json', prices=prices)
    return runtime, local, cfg, primary


def writes(heater):
    return [payload[0]['integerValue'] for payload in heater.writes]


def test_full_scheduled_cycle_in_shadow_preserves_room_driver(tmp_path, heater, monkeypatch):
    r, local, cfg, primary = setup(tmp_path, heater)
    original = deepcopy(cfg)
    monkeypatch.setattr(shadow, 'active', lambda: True)
    assert isinstance(primary, GenericClimateHeatPumpDriver)
    assert primary._entity == 'climate.original_room'
    assert isinstance(local, NibeHotWaterOnlyDriver) and selected(cfg)
    assert run(r, local, cfg, shadow=True)['state'] == 'planned'
    assert run(r, local, cfg, seconds=900, shadow=True)['state'] == 'active'
    assert run(r, local, cfg, seconds=960, temp=60, shadow=True)['state'] == 'complete'
    assert writes(heater) == [3,0]
    assert cfg == original and shadow.active() is True
    assert all(p[0]['variableId'] == 48001 for p in heater.writes)
    assert local.set_room_temp(22) is False
    assert local.set_operating_mode(1) is False
    assert local.set_water_stop_temp(65) is False
    assert local.set_water_start_temp(50) is False
    assert writes(heater) == [3,0]


@pytest.mark.parametrize('changes', [{'live_control_confirmed':False}, {'exclusive_owner_confirmed':False},
                                     {'temperature_role_verified':False}])
def test_shadow_scope_requires_both_explicit_confirmations(tmp_path, heater, monkeypatch, changes):
    r, local, cfg, _ = setup(tmp_path, heater, **changes)
    monkeypatch.setattr(shadow, 'active', lambda: True)
    monkeypatch.setattr(shadow, 'record', Mock())
    assert run(r, local, cfg, shadow=True)['state'] == 'control_blocked'
    assert local.set_hot_water_boost(True) is False
    assert heater.requests == []
    assert not (tmp_path/'control.json').exists()


def test_isolated_driver_rejects_room_write_bindings(tmp_path, heater):
    _, _, cfg, primary = setup(tmp_path, heater)
    cfg['heat_pump']['hot_water_control']['points']['room_target'] = {'register':58}
    with pytest.raises(ValueError):
        house_config.build_hot_water_driver(cfg, primary)
    assert not heater.requests


def test_wrong_demand_mode_waits_without_writing_or_creating_pending_start(tmp_path, heater):
    r, local, cfg, _ = setup(tmp_path, heater)
    heater.points['3697']['value']['integerValue'] = 2
    run(r, local, cfg)
    assert run(r, local, cfg, seconds=900)['state'] == 'planned'
    assert not heater.writes and local._pending is None
    assert heater.points['3697']['value']['integerValue'] == 2
    heater.points['3697']['value']['integerValue'] = 0
    assert run(r, local, cfg, seconds=930)['state'] == 'active'
    assert writes(heater) == [3]


def test_manual_boost_has_one_bounded_attempt_per_override(tmp_path, heater, monkeypatch):
    r, local, cfg, _ = setup(tmp_path, heater)
    monkeypatch.setattr(shadow, 'active', lambda: True)
    assert run(r, local, cfg, shadow=True, manual=True, manual_request='on')['state'] == 'active'
    assert run(r, local, cfg, seconds=900, shadow=True, manual=True, manual_request='on')['state'] == 'complete'
    run(r, local, cfg, seconds=960, shadow=True, manual=True, manual_request='on')
    assert writes(heater) == [3,0]
    run(r, local, cfg, seconds=1000, shadow=True)
    run(r, local, cfg, seconds=1060, shadow=True, manual=True, manual_request='on')
    assert writes(heater) == [3,0,3]


def test_manual_off_releases_owned_boost(tmp_path, heater):
    r, local, cfg, _ = setup(tmp_path, heater)
    run(r, local, cfg, manual=True, manual_request='on')
    assert run(r, local, cfg, seconds=60, manual=True, manual_request='off')['state'] == 'complete'
    assert writes(heater) == [3,0]


def test_manual_on_during_active_scheduled_cycle_does_not_queue_another_boost(tmp_path, heater):
    r, local, cfg, _ = setup(tmp_path, heater)
    run(r, local, cfg)
    run(r, local, cfg, seconds=900)
    run(r, local, cfg, seconds=960, manual=True, manual_request='on')
    assert r.state['manual_consumed'] is True
    run(r, local, cfg, seconds=1800, manual=True, manual_request='on')
    run(r, local, cfg, seconds=1860, manual=True, manual_request='on')
    assert writes(heater) == [3,0]


def test_hygiene_preempts_price_schedule_but_stays_bounded(tmp_path, heater):
    r, local, cfg, _ = setup(tmp_path, heater)
    run(r, local, cfg)
    assert r.controller.state['start'] == NOW+900
    assert run(r, local, cfg, seconds=60, hygiene=True, hygiene_target_c=60)['state'] == 'active'
    assert r.controller.state['attempted_at'] == NOW+60
    assert run(r, local, cfg, seconds=960, hygiene=True, hygiene_target_c=60)['state'] == 'complete'
    assert writes(heater) == [3,0]


def test_hygiene_upgrades_active_target_without_extending_runtime(tmp_path, heater):
    r, local, cfg, _ = setup(tmp_path, heater)
    cfg['heat_pump']['hot_water_control']['comfort_policy']['target_c'] = 55
    run(r, local, cfg)
    run(r, local, cfg, seconds=900)
    end = r.controller.state['end']
    assert run(r, local, cfg, seconds=960, temp=55, hygiene=True, hygiene_target_c=60)['state'] == 'active'
    assert r.controller.state['target_c'] == 60 and r.controller.state['end'] == end
    assert run(r, local, cfg, seconds=1020, temp=60, hygiene=True, hygiene_target_c=60)['state'] == 'complete'
    assert writes(heater) == [3,0]


@pytest.mark.parametrize('guard', ['away','guard_ok'])
def test_priority_requests_do_not_bypass_away_or_electrical_guard(tmp_path, heater, guard):
    r, local, cfg, _ = setup(tmp_path, heater)
    run(r, local, cfg, manual=True, manual_request='on', **{guard:guard=='away'})
    assert heater.writes == []


def test_initial_trigger_seed_is_used_once_and_never_reset_to_cutover_time(tmp_path, heater):
    seed = datetime.fromtimestamp(NOW-600, timezone.utc).isoformat()
    r, local, cfg, _ = setup(tmp_path, heater, initial_trigger_at=seed)
    run(r, local, cfg)
    assert r.state['last_trigger_at'] == NOW-600
    assert r.state['demand']['anchor_at'] == NOW-600
    assert r.controller.state['start'] >= NOW+3000
    cfg['heat_pump']['hot_water_control']['initial_trigger_at'] = datetime.fromtimestamp(NOW-60, timezone.utc).isoformat()
    run(r, local, cfg, seconds=30)
    assert r.state['last_trigger_at'] == NOW-600


@pytest.mark.parametrize('seed', ['2026-11-17T00:00:00Z','2026-11-16T00:00:00','bad'])
def test_invalid_or_future_history_cannot_start_control(tmp_path, heater, seed):
    r, local, cfg, _ = setup(tmp_path, heater, initial_trigger_at=seed)
    assert run(r, local, cfg)['state'] == 'unavailable'
    assert heater.writes == []


def test_scope_withdrawal_and_restart_never_replay_owned_start(tmp_path, heater, monkeypatch):
    r, local, cfg, _ = setup(tmp_path, heater)
    monkeypatch.setattr(shadow, 'active', lambda: True)
    run(r, local, cfg, shadow=True, manual=True, manual_request='on')
    r.journal.lock.close()
    recovered = Runtime(tmp_path/'control.json', prices=prices)
    assert run(recovered, local, cfg, seconds=60, shadow=True)['state'] == 'recovery_required'
    cfg['heat_pump']['hot_water_control']['live_control_confirmed'] = False
    assert run(recovered, local, cfg, seconds=120, shadow=True)['state'] == 'control_blocked'
    assert writes(heater) == [3]


def test_shadow_scope_reporting_is_explicit_and_does_not_expose_configuration(tmp_path, heater):
    _, _, cfg, _ = setup(tmp_path, heater)
    assert shadow.scoped_controls(cfg) == ['hot_water']
    cfg['battery'] = dict(enabled=True,driver='ferroamp_modbus',control='styr',
        default_mode_verified=True,exclusive_owner_confirmed=True,live_control_confirmed=True,modbus={'host':'private'})
    assert shadow.scoped_controls(cfg) == ['hot_water','battery']
    cfg['battery']['control'] = 'samarbete'
    assert shadow.scoped_controls(cfg) == ['hot_water']
    cfg['heat_pump']['hot_water_control']['exclusive_owner_confirmed'] = False
    assert shadow.scoped_controls(cfg) == []
