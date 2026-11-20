"""#395: Growatt hybrid loggar ett skuggrecept och skriver inga register."""
import yaml

from discovery import discover_house
from growatt_shadow import describe, observation
from house_config import battery_settings, build_battery_driver
from i18n_py import tr
from test_solax_modbus_battery import GROWATT, _builder


def _entity(eid, name, dc=None, unit=None, state="40"):
    return {"e": eid, "n": name, "a": None, "d": "dev_growatt", "dn": "Growatt SPH 5000",
            "m": "Growatt", "mo": "SPH 5000", "dc": dc, "u": unit, "st": state}


READ_ONLY = [
    _entity("sensor.growatt_battery_soc", "Battery SOC", "battery", "%", "62"),
    _entity("sensor.growatt_battery_power", "Battery Power", "power", "W", "-400"),
]


def _cfg(**extra):
    battery = {"enabled": True, "control": "samarbete", "max_power_w": 5000, "capacity_kwh": 10}
    battery.update(extra)
    return battery_settings({"battery": battery})


def _state(**extra):
    state = {"soc": 40, "price": 1.2, "meter_fresh": True, "avg_net_w": 800, "battery_w": 0,
             "prices_rest_of_day": [1.2, 1.2, 1.2]}
    state.update(extra)
    return state


def test_growatt_utan_lagen_far_skuggrecept_och_inga_modes():
    battery = discover_house(READ_ONLY)["battery"]
    assert battery["shadow_recipe"] == "growatt_hybrid"
    assert battery["maker"] == "Growatt"
    assert not (battery.get("generic_suggestion") or {}).get("modes")
    assert "skrivs" in battery["note"].lower()
    assert "395" in battery["note"]


def test_time_1_mode_styrs_som_forut_utan_skuggrecept():
    battery = discover_house(GROWATT)["battery"]
    assert battery["control_preset"] == "solax_modbus_growatt"
    assert "shadow_recipe" not in battery


def test_yaml_lamnar_styrningen_i_samarbete():
    text = _builder()({"cars": [], "battery": discover_house(READ_ONLY)["battery"]})
    assert "shadow_recipe: growatt_hybrid" in text
    assert "control: samarbete" in text
    assert "\n  modes:" not in text
    driver = build_battery_driver(yaml.safe_load(text))
    assert driver.supported_intents() == set()


def test_tre_lagen_beskrivs_och_resten_tigs():
    cfg = _cfg()
    assert "1102 = 0 och 1092 = 0" in describe("auto", None, cfg)
    assert "1102 = 1 och 1092 = 0" in describe("hold", None, cfg)
    assert "1102 = 1 och 1092 = 1" in describe("charge", 5000, cfg)
    assert describe("charge", 800, cfg) is None
    assert describe("charge", 3000, _cfg(max_charge_w=2500)) is None
    assert describe("discharge", 5000, cfg) is None
    assert describe("idle", None, cfg) is None
    assert describe("auto", 5000, cfg) is None
    assert describe("hold", 5000, cfg) is None
    for line in (describe("auto", None, cfg), describe("hold", None, cfg), describe("charge", 5000, cfg)):
        assert line.endswith("Skriver inte.")


def test_samarbete_loggar_minuspris_utan_att_andra_laget():
    cfg = _cfg()
    line = observation("growatt_hybrid", _state(price=-0.4), cfg)
    assert "laddar från nätet" in line
    assert "1092 = 1" in line
    assert cfg["control"] == "samarbete"


def test_styrlage_och_okant_recept_ar_tysta():
    cfg = _cfg()
    cfg["control"] = "styr"
    assert observation("growatt_hybrid", _state(price=-0.4), cfg) is None
    assert observation("sofar_g3", _state(price=-0.4), _cfg()) is None
    assert observation("growatt_hybrid", _state(price=-0.4), None) is None


def test_urladdning_vid_sakring_loggas_inte():
    line = observation("growatt_hybrid", _state(fuse_state="overload", fuse_excess_a=10), _cfg())
    assert line is None


def test_elbil_fran_natet_blir_hall_i_skuggan():
    line = observation("growatt_hybrid", _state(ev_charging_grid=True), _cfg())
    assert "håller utan urladdning" in line
    assert "1102 = 1" in line


def test_vila_har_inget_register():
    assert observation("growatt_hybrid", _state(solar_yield_to="elbilen"), _cfg()) is None


def test_loggraden_oversatts():
    line = describe("auto", None, _cfg())
    assert tr(line, "en") == "Growatt shadow: self-consumption, register 1102 = 0 and 1092 = 0. Does not write."
    assert "Nezapisuje" in tr(describe("hold", None, _cfg()), "cs")
    note = discover_house(READ_ONLY)["battery"]["note"]
    assert "No registers are written" in tr(note, "en")
