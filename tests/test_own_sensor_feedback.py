"""2026-11-15: sensor.smartbox_inomhustemp (EnergyWizards egen publicerade innetemperatur) låg bland rumsgivarna.
Medianen läste sitt eget gamla värde och fastnade på 21,1 °C medan rummen svalnade. Egna entiteter räknas aldrig in
och föreslås inte i givarvalet."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import homeassistant


def test_egen_sensor_räknas_inte_in(monkeypatch):
    monkeypatch.setattr(homeassistant, "sensor_config", lambda: {"indoor": [
        {"entity": "sensor.smartbox_inomhustemp", "label": "Smartbox"},
        {"entity": "sensor.timmerflotte_temp", "label": "Vardagsrum", "humidity": "sensor.smartbox_luftfuktighet"}]})
    keys = [s["entity"] for s in homeassistant.indoor_sensors()]
    assert keys == ["sensor.timmerflotte_temp"]
    monkeypatch.setattr(homeassistant, "_get_numeric_state", lambda e: 40.0)
    assert homeassistant.read_humidities() == {}


def test_publicerade_entiteter_känns_igen(monkeypatch):
    monkeypatch.setattr(homeassistant, "_PUBLISHED", set())
    monkeypatch.setattr(homeassistant.requests, "post", lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None, "status_code": 200})())
    homeassistant.publish_states({"sensor.energywizard_test": (1, {})})
    assert homeassistant.is_own_entity("sensor.energywizard_test")
    assert not homeassistant.is_own_entity("sensor.timmerflotte_temp")


def test_givarvalet_föreslår_inte_egna_sensorer():
    src = open(os.path.join(ROOT, "webdashboard", "app.py"), encoding="utf-8").read()
    assert 'or homeassistant.is_own_entity(e):' in src
