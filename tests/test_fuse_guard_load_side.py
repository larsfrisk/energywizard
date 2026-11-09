import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
import fuse_guard


def test_combine_caps_ignores_none_and_takes_lowest():
    assert fuse_guard.combine_caps(None, None) is None
    assert fuse_guard.combine_caps(12, None) == 12
    assert fuse_guard.combine_caps(12, 7) == 7
    assert fuse_guard.combine_caps(0, 9) == 0


def test_merge_trip_limits_takes_lowest_per_car_not_sum():
    grid = {"car1": 10, "car2": 0}
    load = {"car1": 8}
    assert fuse_guard.merge_trip_limits(grid, load) == {"car1": 8, "car2": 0}
    assert fuse_guard.merge_trip_limits({}, {}) == {}
    assert fuse_guard.merge_trip_limits(None, {"car1": 6}) == {"car1": 6}


def _fed(currents, repeats=12, t0=1000.0):
    m = fuse_guard.FuseThermalModel()
    for i in range(repeats):
        m.update(currents, ts=t0 + i * 10)
    return m, t0 + (repeats - 1) * 10


def test_two_points_lowest_cap_wins():
    grid, ts = _fed([6.0, 6.0, 6.0])        # quiet grid side
    load, _ = _fed([17.0, 6.0, 6.0])        # busy load side (L1 near the 20 A limit)
    ev = [0.0, 0.0, 0.0]
    cap_grid = grid.ev_cap_a(20, ev, ts=ts)
    cap_load = load.ev_cap_a(20, ev, ts=ts)
    assert cap_load < cap_grid
    assert fuse_guard.combine_caps(cap_grid, cap_load) == cap_load


def test_emergency_brake_one_decision_for_two_points():
    sent = {"car1": 16}
    grid, ts = _fed([25.0, 5.0, 5.0], repeats=1)    # single reading > 1.2 x 20 A on both points
    load, _ = _fed([26.0, 5.0, 5.0], repeats=1)
    t_grid = fuse_guard.fast_trip_limits(grid, 20, sent, ts=ts)
    t_load = fuse_guard.fast_trip_limits(load, 20, sent, ts=ts)
    merged = fuse_guard.merge_trip_limits(t_grid, t_load)
    assert merged["car1"] == min(t_grid["car1"], t_load["car1"])
    assert merged["car1"] >= 0
    # applying the merged result is ONE cut: 16 - 6 (load excess is larger), not 16 - 5 - 6
    assert merged["car1"] == 16 - 6 or merged["car1"] == 0


def test_stale_load_meter_gives_none_then_conservative_fallback_is_lower_than_fuse():
    load = fuse_guard.FuseThermalModel()            # never fed -> no fresh data
    assert load.ev_cap_a(20, [0, 0, 0], ts=5000.0) is None
    assert fuse_guard.stale_ev_cap_a(20, 0.5) <= fuse_guard.STALE_EV_MAX_A
