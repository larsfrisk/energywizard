"""Directional physical accounting, legacy equivalence and explicit config/replay."""
import math

import pytest

from battery_plan import optimize, simulate
from battery_reference import score
from house_config import battery_settings
import battery_learning
import plan_snapshot as S
from test_plan_snapshot import example


def test_hand_calculated_charge_discharge_and_clipped_power():
    slots = [dict(t=str(i), buy=0, sell=2, load_kw=0, solar_kw=0) for i in range(2)]
    cost, rows = simulate(slots, .5, ['charge', 'discharge'], 2, 0, 2, 1, 1, .9,
                          charge_efficiency=.8, discharge_efficiency=.5)
    assert [r['soc_kwh'] for r in rows] == pytest.approx([.7, .2])
    assert cost == pytest.approx(-.5)
    _, clipped = simulate(slots[:1], 1.9, ['charge'], 2, 0, 2, 1, 1, .9,
                          charge_efficiency=.8, discharge_efficiency=.5)
    assert clipped[0]['soc_kwh'] == 2 and clipped[0]['battery_kw'] == pytest.approx(.5)
    _, clipped = simulate(slots[:1], .1, ['discharge'], 2, .05, 2, 1, 1, .9,
                          charge_efficiency=.8, discharge_efficiency=.5)
    assert clipped[0]['soc_kwh'] == .05 and clipped[0]['battery_kw'] == pytest.approx(-.1)


def test_reference_hand_calculation_uses_independent_directional_accounting():
    slots = [dict(t=str(i), buy=0, sell=2, load_kw=0, solar_kw=0) for i in range(2)]
    p = dict(soc0_kwh=.5, capacity_kwh=2, reserve_kwh=0, max_kwh=2, charge_kw=1, discharge_kw=1,
             charge_efficiency=.8, discharge_efficiency=.5, switch_cost=0)
    cost, rows = score(slots, ['charge', 'discharge'], p)
    assert cost == pytest.approx(-.5) and [r['energy'] for r in rows] == pytest.approx([.7, .2])


def test_legacy_results_are_identical_to_explicit_symmetric_pair():
    slots, p, _, _ = example()
    legacy = optimize(slots, **p)
    symmetric = optimize(slots, **p, charge_efficiency=math.sqrt(p['eff']), discharge_efficiency=math.sqrt(p['eff']))
    assert symmetric == legacy


@pytest.mark.parametrize('pair', [(.9, None), (None, 1), (0, 1), (.9, 1.1), (True, 1), (float('nan'), 1), (.9, float('inf'))])
def test_invalid_or_partial_pair_rejected_by_solver_config_and_snapshot(pair):
    slots, p, _, now = example()
    extra = dict(charge_efficiency=pair[0], discharge_efficiency=pair[1])
    with pytest.raises(ValueError):
        optimize(slots, **p, **extra)
    with pytest.raises(ValueError):
        battery_settings({'battery': {'enabled': True, **extra}})
    with pytest.raises(ValueError):
        S.build(slots, p | extra, optimize(slots, **p), now)


def test_config_snapshot_and_learning_keep_explicit_pair():
    cfg = battery_settings({'battery': {'enabled': True, 'charge_efficiency': '.9', 'discharge_efficiency': '1'}})
    learned = battery_learning.apply(cfg, {'use': {'efficiency': .81}})
    assert learned['efficiency'] == .81
    assert (learned['charge_efficiency'], learned['discharge_efficiency']) == (.9, 1)
    slots, p, _, now = example()
    p.update(charge_efficiency=learned['charge_efficiency'], discharge_efficiency=learned['discharge_efficiency'])
    snap = S.build(slots, p, optimize(slots, **p), now)
    assert snap['inputs']['params']['charge_efficiency'] == .9
    assert S.replay(snap)['matches']


def test_comparison_audit_uses_recorded_directions_instead_of_roundtrip():
    from test_migration_plan_audit import captures, seal
    from migration_plan_audit import audit
    ew, zenai = captures()
    ew['inputs']['params'].update(charge_efficiency=.9, discharge_efficiency=1)
    zenai['output']['plan_details']['objective_assumptions']['discharge_efficiency'] = 1
    assert audit(seal(ew, 'plan_id'), seal(zenai, 'plan_run_id'))['selected_inputs_match']


def test_balancing_hold_uses_directional_energy_and_preserves_ordinary_ceiling():
    slots = [dict(t=str(i), buy=1, sell=0, load_kw=0, solar_kw=0) for i in range(4)]
    p = dict(soc0_kwh=.8, capacity_kwh=1, reserve_kwh=.1, max_kwh=.8, charge_kw=1, discharge_kw=1,
             charge_efficiency=.8, discharge_efficiency=.5, allowed={'auto', 'charge', 'hold'},
             balance_target_kwh=1, balance_hold_slots=1, balance_deadline_slots=4)
    result = optimize(slots, **p)
    assert result['rows']
    assert any(row.get('balance_hold') and row['soc_kwh'] == 1 for row in result['rows'])
    assert p['max_kwh'] == .8


def test_measured_self_use_baseline_obeys_explicit_discharge_efficiency():
    from battery_baseline import compare
    slots = [dict(t=str(i), grid_kw=1, solar_kw=0, battery_kw=0, buy=2, sell=0) for i in range(2)]
    result = compare(slots, .5, 1, 0, 1, 1, 1, .9, charge_efficiency=.8, discharge_efficiency=1)
    assert result['actual'] == 1 and result['selfuse'] == 0 and result['saved'] == -1


def test_paired_forecast_cash_and_end_energy_match_independent_physics():
    from test_load_forecast_evaluation import history, planner_snapshot
    from load_forecast_evaluation import evaluate_planner_snapshot
    snapshot = planner_snapshot(charge_efficiency=.9, discharge_efficiency=1)
    result = evaluate_planner_snapshot(history(), snapshot, 'UTC')
    actual_slots = [dict(s, load_kw=1) for s in snapshot['inputs']['slots']]
    for scenario in result['results'].values():
        _, physical = score(actual_slots, scenario['actions'], snapshot['inputs']['params'])
        cash = sum(r['grid'] * .25 * s['buy' if r['grid'] >= 0 else 'sell'] for r, s in zip(physical, actual_slots))
        assert scenario['energy_cash_cost'] == pytest.approx(cash)
        assert scenario['ending_soc_kwh'] == pytest.approx(physical[-1]['energy'])
    assert not result['adoption_ready']


def test_snapshot_identity_binds_directional_model_source(monkeypatch):
    slots, p, result, now = example()
    snap = S.build(slots, p, result, now)
    original_read = S.Path.read_bytes
    def changed_source(path):
        data = original_read(path)
        return data + b'\n# changed model\n' if path.name == 'battery_efficiency.py' else data
    try:
        with monkeypatch.context() as patch:
            patch.setattr(S.Path, 'read_bytes', changed_source)
            S.planner_hash.cache_clear()
            with pytest.raises(ValueError, match='version'):
                S.replay(snap)
    finally:
        S.planner_hash.cache_clear()
