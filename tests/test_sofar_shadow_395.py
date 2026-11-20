"""#395: Sofar HYD loggar ett skuggrecept och skriver inga register."""
import yaml

from discovery import discover_house
from house_config import battery_settings, build_battery_driver
from sofar_shadow import describe, observation
from test_solax_modbus_battery import _builder


def _entity(eid, name, dc=None, unit=None, state="40"):
    return {"e": eid, "n": name, "a": None, "d": "dev_sofar", "dn": "Sofar HYD 5000",
            "m": "Sofar", "mo": "HYD 5000-ES", "dc": dc, "u": unit, "st": state}


SOFAR = [
    _entity("sensor.sofar_battery_soc", "Battery SOC", "battery", "%", "62"),
    _entity("sensor.sofar_battery_power", "Battery Power", "power", "W", "-400"),
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


def test_sofar_utan_lagen_far_skuggrecept_och_inga_modes():
    battery = discover_house(SOFAR)["battery"]
    assert battery["shadow_recipe"] == "sofar_g3"
    assert battery["maker"] == "Sofar"
    assert not (battery.get("generic_suggestion") or {}).get("modes")
    assert "Skriver" in battery["note"] or "skriv" in battery["note"].lower()
    assert "#395" in battery["note"]


def test_yaml_lamnar_styrningen_i_samarbete():
    text = _builder()({"cars": [], "battery": discover_house(SOFAR)["battery"]})
    assert "shadow_recipe: sofar_g3" in text
    assert "control: samarbete" in text
    assert "\n  modes:" not in text
    driver = build_battery_driver(yaml.safe_load(text))
    assert driver.supported_intents() == set()


def test_hela_effekten_beskrivs_och_en_del_effekt_tigs():
    cfg = _cfg()
    assert "0x1110 = 0" in describe("auto", None, cfg)
    assert "min 0 W och max 5000 W" in describe("hold", None, cfg)
    assert "min och max 5000 W" in describe("charge", 5000, cfg)
    assert "min och max -5000 W" in describe("discharge", 5000, cfg)
    assert describe("charge", 800, cfg) is None
    assert describe("discharge", 828, cfg) is None
    assert describe("idle", None, cfg) is None
    assert describe("auto", 5000, cfg) is None
    for line in (describe("auto", None, cfg), describe("charge", 5000, cfg)):
        assert line.endswith("Skriver inte.")


def test_samarbete_loggar_minuspris_utan_att_andra_laget():
    cfg = _cfg()
    line = observation("sofar_g3", _state(price=-0.4), cfg)
    assert "laddar" in line
    assert "5000" in line
    assert cfg["control"] == "samarbete"


def test_styrlage_och_okant_recept_ar_tysta():
    cfg = _cfg()
    cfg["control"] = "styr"
    assert observation("sofar_g3", _state(price=-0.4), cfg) is None
    assert observation("annat", _state(price=-0.4), _cfg()) is None


def test_delad_urladdning_vid_sakring_loggas_inte():
    cfg = _cfg()
    line = observation("sofar_g3", _state(fuse_state="overload", fuse_excess_a=1), cfg)
    assert line is None


def test_elbil_fran_natet_blir_hall_i_skuggan():
    line = observation("sofar_g3", _state(ev_charging_grid=True), _cfg())
    assert "håller utan urladdning" in line
    assert "0x1110 = 3" in line


def test_vila_har_inget_register():
    assert observation("sofar_g3", _state(solar_yield_to="elbilen"), _cfg()) is None
