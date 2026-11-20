"""#447: spabadets filtercykel vilar på dyr el och körs på billig, i skugga tills control är true."""
from datetime import datetime, timedelta

import spa_filter


def _cfg(**kw):
    base = {"enabled": True, "switch": "switch.spa_filter"}
    base.update(kw)
    return base


def _t(hour, minute=0):
    return datetime(2026, 11, 20, hour, minute)


def test_disabled_and_invalid_switch_do_not_control():
    assert spa_filter.settings(None) is None
    assert spa_filter.settings({"enabled": False, "switch": "switch.spa_filter"}) is None
    cfg = spa_filter.settings(_cfg(switch="binary_sensor.circ", control=True))
    assert cfg["switch"] is None
    assert cfg["control"] is False
    assert spa_filter.settings(_cfg(control=True))["control"] is True


def test_daily_target_is_at_least_the_minimum():
    cfg = spa_filter.settings(_cfg(min_minutes=300, daily_minutes=60))
    assert cfg["min_minutes"] == 300
    assert cfg["daily_minutes"] == 300


def test_expensive_rests_only_after_the_minimum():
    cfg = spa_filter.settings(_cfg(min_minutes=120, daily_minutes=240))
    assert spa_filter.advise(
        _t(18), "EXPENSIVE", True, heating_now=False, in_bath=False, bath_at=None,
        minutes_today=119, cfg=cfg)[0] is None
    action, why = spa_filter.advise(
        _t(18), "EXPENSIVE", True, heating_now=False, in_bath=False, bath_at=None,
        minutes_today=120, cfg=cfg)
    assert action == "vila"
    assert "120" in why


def test_cheap_runs_until_the_daily_target():
    cfg = spa_filter.settings(_cfg())
    assert spa_filter.advise(
        _t(3), "CHEAP", False, heating_now=False, in_bath=False, bath_at=None,
        minutes_today=239, cfg=cfg)[0] == "kör"
    assert spa_filter.advise(
        _t(3), "CHEAP", False, heating_now=False, in_bath=False, bath_at=None,
        minutes_today=240, cfg=cfg)[0] is None
    assert spa_filter.advise(
        _t(3), "CHEAP", True, heating_now=False, in_bath=False, bath_at=None,
        minutes_today=10, cfg=cfg)[0] is None


def test_heat_bath_and_unknown_cycle_are_left_alone():
    cfg = spa_filter.settings(_cfg(bath_hold_minutes=180))
    soon = _t(18) + timedelta(hours=2)
    for kwargs in (
        {"heating_now": True, "in_bath": False, "bath_at": None, "on": True, "price": "EXPENSIVE", "minutes": 200},
        {"heating_now": False, "in_bath": True, "bath_at": None, "on": True, "price": "EXPENSIVE", "minutes": 200},
        {"heating_now": False, "in_bath": False, "bath_at": soon, "on": True, "price": "EXPENSIVE", "minutes": 200},
        {"heating_now": False, "in_bath": False, "bath_at": None, "on": None, "price": "EXPENSIVE", "minutes": 200},
    ):
        action, _why = spa_filter.advise(
            _t(18), kwargs["price"], kwargs["on"], heating_now=kwargs["heating_now"],
            in_bath=kwargs["in_bath"], bath_at=kwargs["bath_at"], minutes_today=kwargs["minutes"], cfg=cfg)
        assert action is None


def test_signals_from_gecko_and_balboa():
    assert spa_filter.circulating({"circ_pump": True, "heating": False}) is True
    assert spa_filter.circulating({"filter_switch": "off"}) is False
    assert spa_filter.circulating({"pump1": "on"}) is None
    assert spa_filter.heating({"heating": "on"}, "idle") is True
    assert spa_filter.heating({}, "heat") is True
    assert spa_filter.heating({}, "idle") is False


def test_minutes_and_energy_follow_circulation_only():
    policy = spa_filter.Policy(_cfg())
    policy.tick(_t(12, 0), "EXPENSIVE", {"circ_pump": True}, "idle", False, None, 200,
                write=lambda *_: False, record=lambda *_: None, shadow_on=True)
    policy.tick(_t(12, 1), "EXPENSIVE", {"circ_pump": True}, "idle", False, None, 200,
                write=lambda *_: False, record=lambda *_: None, shadow_on=True)
    assert policy.minutes == 1
    assert policy.expensive_minutes == 1
    assert abs(policy.wh - 200 / 60) < 1e-6
    policy.tick(_t(12, 2), "EXPENSIVE", {"circ_pump": True, "heating": True}, "idle", False, None, 2000,
                write=lambda *_: False, record=lambda *_: None, shadow_on=True)
    assert policy.minutes == 2
    assert abs(policy.wh - 200 / 60) < 1e-6
    policy.tick(_t(0, 0) + timedelta(days=1), "CHEAP", {"circ_pump": False}, "idle", False, None, None,
                write=lambda *_: False, record=lambda *_: None, shadow_on=True)
    assert policy.minutes == 0
    assert policy.wh == 0


def test_shadow_records_and_does_not_write():
    policy = spa_filter.Policy(_cfg(control=False, min_minutes=0))
    calls = []
    notes = []
    policy.tick(_t(12), "CHEAP", {"circ_pump": False}, "idle", False, None, None,
                write=lambda *a: calls.append(a), record=lambda *a: notes.append(a), shadow_on=False)
    policy.tick(_t(12, 1), "EXPENSIVE", {"circ_pump": True}, "idle", False, None, None,
                write=lambda *a: calls.append(a), record=lambda *a: notes.append(a), shadow_on=False)
    assert calls == []
    assert notes[0][0] == "spabadets filtercykel"
    assert notes[0][1].startswith("kör:")
    assert notes[1][1].startswith("vila:")


def test_control_writes_only_when_the_cycle_should_change():
    policy = spa_filter.Policy(_cfg(control=True, min_minutes=0, dwell_minutes=30))
    calls = []
    notes = []

    def write(entity, on):
        calls.append((entity, on))
        return True

    policy.tick(_t(1), "CHEAP", {"filter_switch": "off"}, "idle", False, None, None,
                write=write, record=lambda *a: notes.append(a), shadow_on=False)
    policy.tick(_t(1, 5), "CHEAP", {"filter_switch": "off"}, "idle", False, None, None,
                write=write, record=lambda *a: notes.append(a), shadow_on=False)
    policy.tick(_t(2), "CHEAP", {"filter_switch": "on"}, "idle", False, None, None,
                write=write, record=lambda *a: notes.append(a), shadow_on=False)
    assert calls == [("switch.spa_filter", True)]
    assert notes == []
    policy.tick(_t(2, 1), "CHEAP", {"filter_switch": "off"}, "idle", False, None, None,
                write=write, record=lambda *a: notes.append(a), shadow_on=True)
    assert calls == [("switch.spa_filter", True)]
    assert notes == [("spabadets filtercykel", "kör: billig el")]
