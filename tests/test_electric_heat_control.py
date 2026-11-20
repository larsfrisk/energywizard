"""#431: elvärme med egen termostat. Skugga tills control är true."""
from datetime import datetime, timedelta

import yaml

import discovery
import electric_heat_control as electric_heat
from discovery import discover_house


def _zone(**kw):
    base = {"entity": "climate.sovrum", "min_c": 15, "max_c": 21}
    base.update(kw)
    return base


def _cfg(*items, control=False):
    return {"enabled": True, "control": control, "zones": list(items)}


def _monday(hour, minute=0):
    day = datetime(2026, 11, 16)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day.replace(hour=hour, minute=minute)


def test_disabled_and_invalid_zones_are_skipped():
    assert electric_heat.zones(None) == []
    assert electric_heat.zones({"enabled": True, "zones": [
        {"entity": "climate.ok", "min_c": 21, "max_c": 15},
        {"entity": "number.x", "min_c": 15, "max_c": 21},
        _zone(), _zone(entity="climate.sovrum"),
    ]})[0]["entity"] == "climate.sovrum"
    assert len(electric_heat.zones({"enabled": True, "zones": [
        _zone(entity=f"climate.z{i}") for i in range(20)]})) == 16


def test_price_solar_schedule_away_and_summer():
    zone = electric_heat.zones(_cfg(_zone(schedule=[{"days": [0], "start": "06:00", "end": "09:00", "temp_c": 20}])))[0]
    assert electric_heat.target_for(zone, _monday(12), "EXPENSIVE", False, False, False) == (15, "dyrt")
    assert electric_heat.target_for(zone, _monday(12), "CHEAP", False, False, False) == (21, "billigt")
    assert electric_heat.target_for(zone, _monday(12), "EXPENSIVE", True, False, False) == (21, "solöverskott")
    assert electric_heat.target_for(zone, _monday(7), "EXPENSIVE", True, False, False) == (20, "schema")
    assert electric_heat.target_for(zone, _monday(7), "CHEAP", False, False, True) == (15, "borta")
    assert electric_heat.target_for(zone, _monday(12), "CHEAP", True, True, False) == (15, "sommar")
    assert electric_heat.target_for(zone, _monday(12), None, False, False, False) == (None, None)
    late = _zone(schedule=[{"days": [0], "start": "22:00", "end": "06:00", "temp_c": 19}])
    night = electric_heat.zones(_cfg(late))[0]
    assert electric_heat.target_for(night, _monday(23), "EXPENSIVE", False, False, False)[1] == "schema"
    assert electric_heat.target_for(night, _monday(5), "EXPENSIVE", False, False, False)[1] == "schema"
    assert electric_heat.target_for(night, _monday(12), "EXPENSIVE", False, False, False)[1] == "dyrt"


def test_tick_holds_grey_zone_and_writes_only_when_control_is_on():
    ctrl = electric_heat.Controller(_cfg(_zone()))
    calls, records = [], []

    def write(entity, target):
        calls.append((entity, target))

    def record(what, detail):
        records.append((what, detail))
    now = _monday(12)
    assert ctrl.tick(now, 1.0, 1.0, 0.1, 0, False, False, False, lambda _e: 18, write, record, False) == []
    assert ctrl.tick(now, 2.0, 1.0, 0.1, 0, False, False, False, lambda _e: 18, write, record, False) == [
        "climate.sovrum 15.0 °C (dyrt)"]
    assert records and calls == []
    live = electric_heat.Controller(_cfg(_zone(), control=True))
    assert live.tick(now, 0.1, 1.0, 0.1, 0, False, False, True, lambda _e: 15, write, record, False) == []
    assert live.tick(now, 2.0, 1.0, 0.1, -2000, False, False, False, lambda _e: 15.1, write, record, True) == [
        "climate.sovrum 21.0 °C (solöverskott)"]
    assert calls == []
    assert live.tick(now, 2.0, 1.0, 0.1, -2000, False, False, False, lambda _e: 21, write, record, False) == []
    assert live.tick(now, 0.1, 1.0, 0.1, 0, False, False, False, lambda _e: 15, write, record, False) == [
        "climate.sovrum 21.0 °C (billigt)"]
    assert calls == [("climate.sovrum", 21.0)]


def test_power_is_explained_once():
    cfg = _cfg(_zone(power="sensor.a"), _zone(entity="climate.hall", power="sensor.a"),
               _zone(entity="climate.kok", power="sensor.kok"))
    assert electric_heat.loads(cfg) == [
        {"name": "climate.sovrum", "entities": ["sensor.a"]},
        {"name": "climate.kok", "entities": ["sensor.kok"]},
    ]


def test_discovery_lists_floor_heat_not_the_heat_pump(monkeypatch):
    monkeypatch.setattr(discovery, "_check_configured_heat_pump", lambda: None)
    entities = [
        dict(e="climate.sensibo", n="Element", m="Sensibo", d="hp"),
        dict(e="climate.golv", n="Golvvärme kök", m="Zigbee", d="floor", a="Kök"),
        dict(e="sensor.golv_w", n="Effekt", m="Zigbee", d="floor", dc="power", u="W"),
        dict(e="sensor.golv_2", n="Annan", m="Zigbee", d="floor", dc="power", u="W"),
        dict(e="climate.fake", n="Adax", m="Other", d="x"),
    ]
    found = discover_house(entities)
    assert found["heat_pump"]["maker"] == "Sensibo"
    assert found["radiators"] == [
        {"entity": "climate.golv", "name": "Golvvärme kök", "area": "Kök", "maker": "Zigbee"}]
    one = discover_house(entities[:3] + entities[4:])
    assert one["radiators"][0]["power"] == "sensor.golv_w"


def test_guide_writes_shadow_config(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    monkeypatch.chdir(root / "webdashboard")
    name = "webdashboard_app_heat"
    spec = importlib.util.spec_from_file_location(name, root / "webdashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    text = mod._build_house_config_yaml({"heaters": [{
        "entity": "climate.golv", "name": "Kök", "min_c": 16, "max_c": 21, "power": "sensor.golv_w"}]})
    cfg = yaml.safe_load(text)
    assert cfg["electric_heat"]["control"] is False
    assert cfg["electric_heat"]["zones"] == [{
        "entity": "climate.golv", "name": "Kök", "min_c": 16, "max_c": 21, "power": "sensor.golv_w"}]
    assert "electric_heat" not in yaml.safe_load(mod._build_house_config_yaml({}))
