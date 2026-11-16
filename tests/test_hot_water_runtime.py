"""Runtime integration with fake heater/prices and real private journal files."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from test_heatpump_nibe_local import heater as local_heater, boost_driver

from hot_water_runtime import Runtime, Journal, permitted, selected
from hot_water_observation import temperature


T = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
NOW = T.timestamp()
POLICY = {'comfort_c': 38, 'target_c': 60, 'max_trigger_age_s': 7200,
          'min_trigger_interval_s': 3600, 'comfort_window_s': 1800,
          'comfort_bypasses_interval': False, 'duration_min': 15,
          'electrical_power_kw': 2.5, 'max_age_s': 90, 'allow_receipt': True}


class Heater:
    value = False
    deliver = True

    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {'hot_water_boost'}

    def read_hot_water_boost(self):
        return self.value

    def set_hot_water_boost(self, active):
        self.calls.append(active)
        if self.deliver:
            self.value = active
        return True


def house():
    return {'heat_pump': {'enabled': True, 'driver': 'nibe_local', 'control_enabled': True,
            'connection': {'expected_product': 'synthetic', 'password': 'never-publish'},
            'points': {'hot_water_boost': {'synthetic': True}},
            'hot_water_control': {'enabled': True, 'exclusive_owner_confirmed': True,
                'temperature_role_verified': True, 'max_runtime_s': 900,
                'comfort_policy': deepcopy(POLICY)}}}


def prices(now):
    return [{'t': (T + timedelta(minutes=15*i)).isoformat(), 'buy': cost}
            for i, cost in enumerate([5, 1, 4, 4, 4, 4, 4, 4])]


def run(runtime, heater, config=None, seconds=0, temp=40, **changes):
    flags = dict(shadow=False, manual=False, away=False, hygiene=False, guard_ok=True)
    flags.update(changes)
    return runtime.tick(house() if config is None else config, heater,
        temperature(temp, (T + timedelta(seconds=seconds)).isoformat(), 'local_receipt'),
        now=NOW + seconds, **flags)


def runtime(tmp_path):
    return Runtime(tmp_path / 'control.json', prices=prices)


def test_runtime_selects_cheapest_window_then_stops_at_target(tmp_path):
    r, h = runtime(tmp_path), Heater()
    assert run(r, h)['state'] == 'planned'
    assert r.controller.state['start'] == NOW + 900
    assert h.calls == []
    assert run(r, h, seconds=900)['state'] == 'active'
    assert run(r, h, seconds=960, temp=60)['state'] == 'complete'
    assert h.calls == [True, False]
    saved = json.loads((tmp_path / 'control.json').read_text())
    assert saved['last_trigger_at'] == NOW + 900
    assert 'never-publish' not in json.dumps(saved)


def test_repeated_cycle_keeps_real_trigger_interval(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    run(r, h, seconds=900)
    run(r, h, seconds=960, temp=60)
    run(r, h, seconds=1020)
    assert r.controller.state['start'] >= NOW + 4500
    assert r.state['demand']['anchor_at'] == NOW + 900
    assert h.calls == [True, False]


@pytest.mark.parametrize('change', ['disabled', 'shadow', 'owner', 'role', 'control', 'unsupported'])
def test_initial_gates_do_not_open_journal_or_query_prices(tmp_path, change):
    def forbidden(*args):
        pytest.fail('Blocked runtime performed I/O')
    r, h, cfg = Runtime(prices=forbidden, journal_factory=forbidden), Heater(), house()
    hp, flags = cfg['heat_pump'], {}
    if change == 'disabled':
        hp['hot_water_control']['enabled'] = False
    elif change == 'shadow':
        flags['shadow'] = True
    elif change == 'owner':
        hp['hot_water_control']['exclusive_owner_confirmed'] = False
    elif change == 'role':
        hp['hot_water_control']['temperature_role_verified'] = False
    elif change == 'control':
        hp['control_enabled'] = False
    else:
        h.capabilities = lambda: set()
    run(r, h, cfg, **flags)
    assert h.calls == []


@pytest.mark.parametrize('guard', ['manual', 'away', 'hygiene', 'guard_ok'])
def test_precedence_prevents_new_plan(tmp_path, guard):
    r, h = runtime(tmp_path), Heater()
    run(r, h, **{guard: guard != 'guard_ok'})
    assert h.calls == []
    assert not r.controller.state


def test_restart_active_requires_operator_recovery_without_commands(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    run(r, h, seconds=900)
    r.journal.lock.close()  # Simulate process exit; durable state remains.
    recovered = runtime(tmp_path)
    assert run(recovered, h, seconds=960)['state'] == 'recovery_required'
    assert h.calls == [True]


def test_restart_planned_replans_without_replaying_old_start(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    r.journal.lock.close()
    recovered = runtime(tmp_path)
    assert run(recovered, h, seconds=30)['state'] == 'planned'
    assert h.calls == []


def test_second_process_cannot_own_same_journal(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    second = runtime(tmp_path)
    assert run(second, h)['state'] == 'unavailable'
    assert h.calls == []


def test_corrupt_existing_journal_is_not_treated_as_empty(tmp_path):
    path = tmp_path / 'control.json'
    path.write_text('{bad')
    r, h = runtime(tmp_path), Heater()
    assert run(r, h)['state'] == 'unavailable'
    assert path.read_text() == '{bad'
    assert h.calls == []


def test_context_change_blocks_without_reset(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    run(r, h, cfg)
    cfg['heat_pump']['points']['hot_water_boost']['synthetic'] = False
    assert run(r, h, cfg, seconds=900)['state'] == 'unavailable'
    assert h.calls == []


def test_store_failure_before_start_prevents_command(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    def fail(state):
        raise OSError('secret endpoint')
    r.journal.save = fail
    result = run(r, h, seconds=900)
    assert result['state'] == 'storage_error'
    assert 'secret' not in json.dumps(result)
    assert h.calls == []


def test_missing_prices_never_start_or_reset_demand_deadline(tmp_path):
    r, h = runtime(tmp_path), Heater()
    r.prices = lambda now: []
    run(r, h)
    anchor = r.state['demand']['anchor_at']
    run(r, h, seconds=60)
    assert r.state['demand']['anchor_at'] == anchor
    assert h.calls == []


def test_ambiguous_start_survives_ticks_and_restart(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    h.deliver = False
    assert run(r, h, seconds=900)['state'] == 'start_pending'
    run(r, h, seconds=960)
    r.journal.lock.close()
    recovered = runtime(tmp_path)
    assert run(recovered, h, seconds=1020)['state'] == 'recovery_required'
    assert h.calls == [True]


def test_guard_loss_releases_owned_cycle(tmp_path):
    r, h = runtime(tmp_path), Heater()
    run(r, h)
    run(r, h, seconds=900)
    assert run(r, h, seconds=960, guard_ok=False)['state'] == 'complete'
    assert h.calls == [True, False]


def test_journal_permissions_and_strict_round_trip(tmp_path):
    journal = Journal(tmp_path / 'strict.json')
    journal.save({'cycle': {}, 'schema': 1})
    assert journal.load() == {'cycle': {}, 'schema': 1}
    assert journal.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        journal.save({'bad': float('nan')})
    assert journal.load() == {'cycle': {}, 'schema': 1}


def guard(**changes):
    return permitted(**{**dict(meter_fresh=True, fuse_fresh=True, currents=[1, 2, 3],
        filtered=[1, 2, 3], fuse_a=25, margin_a=2, peak_ok=True, additional_kw=2.5), **changes})


@pytest.mark.parametrize('changes', [{'meter_fresh': False}, {'fuse_fresh': False},
    {'peak_ok': False}, {'currents': [float('nan'), 0, 0]}, {'filtered': []},
    {'currents': [20, 2, 3]}, {'additional_kw': True}])
def test_start_guard_refuses_unknown_stale_or_insufficient_headroom(changes):
    assert not guard(**changes)


def test_guard_includes_extra_start_power_but_not_double_counts_active_power():
    assert guard()
    assert not guard(currents=[20, 2, 3])
    assert guard(currents=[20, 2, 3], additional_kw=0)


def test_engine_calls_runtime_and_gates_legacy_setpoint_writer():
    # Inspect the engine AST instead of importing its startup side effects.
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'smartbox/main.py').read_text(encoding='utf-8'))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert any(ast.unparse(n.func) == '_hot_water_runtime.tick' for n in calls)
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and any(isinstance(c, ast.Call) and ast.unparse(c.func) == 'water_sp.apply'
                      for statement in n.body for c in ast.walk(statement))]
    assert any('_hw_selected' in ast.unparse(n.test) and '_hw_hygiene' in ast.unparse(n.test)
               and '_hw_manual' in ast.unparse(n.test) for n in writes)


def test_selection_requires_explicit_nibe_opt_in():
    assert not selected({})
    assert selected(house())
    cfg = house()
    cfg['heat_pump']['driver'] = 'myuplink'
    assert not selected(cfg)


def test_runtime_through_native_driver_writes_exact_boost_and_release(tmp_path, local_heater):
    r = runtime(tmp_path)
    driver = boost_driver(local_heater)
    run(r, driver)
    assert run(r, driver, seconds=900)['state'] == 'active'
    assert run(r, driver, seconds=960, temp=60)['state'] == 'complete'
    assert [p[0]['integerValue'] for p in local_heater.writes] == [3, 0]
    assert all(p[0]['variableId'] == 48001 for p in local_heater.writes)
    assert local_heater.requests[-1][0] == 'GET'


def test_runtime_through_native_driver_never_replays_delayed_start(tmp_path, local_heater):
    r = runtime(tmp_path)
    driver = boost_driver(local_heater)
    run(r, driver)
    local_heater.apply = False
    assert run(r, driver, seconds=900)['state'] == 'start_pending'
    run(r, driver, seconds=960)
    assert len(local_heater.writes) == 1
    local_heater.points['48001']['value']['integerValue'] = 3
    local_heater.apply = True
    assert run(r, driver, seconds=1800)['state'] == 'complete'
    assert [p[0]['integerValue'] for p in local_heater.writes] == [3, 0]


def test_runtime_accepts_longer_trigger_age_without_extending_planner(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    cfg['heat_pump']['hot_water_control']['comfort_policy']['max_trigger_age_s'] = 42 * 3600
    assert run(r, h, cfg)['state'] == 'planned'
    assert r.controller.state['deadline'] == NOW + 36 * 3600


def test_disabling_active_control_invalidates_authority_without_release(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    run(r, h, cfg)
    run(r, h, cfg, seconds=900)
    cfg['heat_pump']['hot_water_control']['enabled'] = False
    assert run(r, h, cfg, seconds=960)['state'] == 'disabled'
    cfg['heat_pump']['hot_water_control']['enabled'] = True
    assert run(r, h, cfg, seconds=1020)['state'] == 'interrupted'
    assert h.calls == [True]
