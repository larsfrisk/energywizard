"""#395: AlphaESS SMILE loggar ett skuggrecept och skriver inga register."""
import yaml

from alphaess_shadow import describe, observation
from discovery import discover_house
from house_config import battery_settings, build_battery_driver
from i18n_py import tr
from test_solax_modbus_battery import _builder


def _entity(eid, name, dc=None, unit=None, state="40", maker="Alpha ESS", device="Storion SMILE"):
    return {"e": eid, "n": name, "a": None, "d": "dev_alpha", "dn": device,
            "m": maker, "mo": "SMILE5", "dc": dc, "u": unit, "st": state}


READ_ONLY = [
    _entity("sensor.alphaess_battery_soc", "Battery SOC", "battery", "%", "58"),
    _entity("sensor.alphaess_battery_power", "Battery Power", "power", "W", "-200"),
]


def _cfg(**extra):
    battery = {"enabled": True, "control": "samarbete", "max_power_w": 5000,
               "capacity_kwh": 10, "max_soc": 100}
    battery.update(extra)
    return battery_settings({"battery": battery})


def _state(**extra):
    state = {"soc": 40, "price": 1.2, "meter_fresh": True, "avg_net_w": 800, "battery_w": 0,
             "prices_rest_of_day": [1.2, 1.2, 1.2]}
    state.update(extra)
    return state


def test_alphaess_utan_lagen_far_skuggrecept_och_inga_modes():
    battery = discover_house(READ_ONLY)["battery"]
    assert battery["shadow_recipe"] == "alphaess_smile"
    assert battery["maker"] == "Alpha ESS"
    assert not (battery.get("generic_suggestion") or {}).get("modes")
    assert "skrivs" in battery["note"].lower()
    assert "395" in battery["note"]


def test_storion_far_samma_recept():
    ents = [
        _entity("sensor.storion_soc", "Battery SOC", "battery", "%", "44",
                maker="Storion", device="Storion SMILE-B3"),
        _entity("sensor.storion_power", "Battery Power", "power", "W", "0",
                maker="Storion", device="Storion SMILE-B3"),
    ]
    assert discover_house(ents)["battery"]["shadow_recipe"] == "alphaess_smile"


def test_annat_batteri_far_inte_receptet():
    ents = [
        _entity("sensor.other_soc", "Battery SOC", "battery", "%", "50",
                maker="Okänt", device="Husbatteri"),
        _entity("sensor.other_power", "Battery Power", "power", "W", "100",
                maker="Okänt", device="Husbatteri"),
    ]
    assert "shadow_recipe" not in discover_house(ents)["battery"]


def test_yaml_lamnar_styrningen_i_samarbete():
    text = _builder()({"cars": [], "battery": discover_house(READ_ONLY)["battery"]})
    assert "shadow_recipe: alphaess_smile" in text
    assert "control: samarbete" in text
    assert "\n  modes:" not in text
    driver = build_battery_driver(yaml.safe_load(text))
    assert driver.supported_intents() == set()


def test_tre_lagen_beskrivs_och_resten_tigs():
    cfg = _cfg()
    assert "2176 = 0" in describe("auto", None, cfg)
    assert "2177 = 27000" in describe("hold", None, cfg)
    assert "2181 = 1" in describe("hold", None, cfg)
    assert "2182 = 250 (100 %)" in describe("charge", 5000, cfg)
    assert "2182 = 225 (90 %)" in describe("charge", 2500, _cfg(max_charge_w=2500, max_soc=90))
    assert describe("charge", 800, cfg) is None
    assert describe("charge", 5000, _cfg(max_soc=99)) is None
    assert describe("charge", 5000, _cfg(max_soc=100.4)) is None
    assert describe("discharge", 5000, cfg) is None
    assert describe("idle", None, cfg) is None
    assert describe("auto", 5000, cfg) is None
    assert describe("hold", 5000, cfg) is None
    assert describe("hold", None, {"max_power_w": 0}) is None
    for line in (describe("auto", None, cfg), describe("hold", None, cfg), describe("charge", 5000, cfg)):
        assert line.endswith("Skriver inte.")
        assert "120 s" in line or "2176 = 0" in line


def test_samarbete_loggar_minuspris_utan_att_andra_laget():
    cfg = _cfg()
    line = observation("alphaess_smile", _state(price=-0.4), cfg)
    assert "laddar från nätet" in line
    assert "2177 = 27000" in line
    assert "2182 = 250" in line
    assert cfg["control"] == "samarbete"


def test_styrlage_och_okant_recept_ar_tysta():
    cfg = _cfg()
    cfg["control"] = "styr"
    assert observation("alphaess_smile", _state(price=-0.4), cfg) is None
    assert observation("saj_h2", _state(price=-0.4), _cfg()) is None
    assert observation("alphaess_smile", _state(price=-0.4), None) is None


def test_urladdning_vid_sakring_loggas_inte():
    line = observation("alphaess_smile", _state(fuse_state="overload", fuse_excess_a=10), _cfg())
    assert line is None


def test_elbil_fran_natet_blir_hall_i_skuggan():
    line = observation("alphaess_smile", _state(ev_charging_grid=True), _cfg())
    assert "håller utan urladdning" in line
    assert "2177 = 27000" in line
    assert "120 s" in line


def test_vila_och_delad_laddning_har_inget_register():
    assert observation("alphaess_smile", _state(solar_yield_to="elbilen"), _cfg()) is None
    assert observation("alphaess_smile", _state(planned_action="charge", planned_power_w=800), _cfg()) is None


def test_udda_laddtak_har_inget_register():
    assert observation("alphaess_smile", _state(price=-0.4), _cfg(max_soc=99)) is None


def test_loggraden_oversatts():
    line = describe("auto", None, _cfg())
    assert tr(line, "en") == "AlphaESS shadow: self-consumption, register 2176 = 0 (dispatch off). Does not write."
    assert "Nezapisuje" in tr(describe("hold", None, _cfg()), "cs")
    assert "27000" in tr(describe("hold", None, _cfg()), "en")
    assert "250" in tr(describe("charge", 5000, _cfg()), "cs")
    note = discover_house(READ_ONLY)["battery"]["note"]
    assert "No registers are written" in tr(note, "en")
