"""#570: Gecko-badet upptäcktes med climate-entiteten som "temperatur" och EnergyWizards egen sensor som effektkälla, så
temperaturen visades aldrig, badet räknades som offline och ingenting gick att styra."""
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "smartbox"))
import discovery  # noqa: E402
import homeassistant  # noqa: E402
import house_config  # noqa: E402
import spa_entities  # noqa: E402
from drivers.spa_gecko import GeckoSpaDriver  # noqa: E402

# Entiteterna i ett Gecko-bad enligt mönstret i en fungerande installation (config/examples/emil_house.yaml)
NAMES = {
    "climate.erik_spa_heater": "Erik spa Heater",
    "sensor.erik_spa_current_temperature": "Erik spa Current temperature",
    "sensor.erik_spa_target_temperature": "Erik spa Target temperature",
    "water_heater.erik_spa_heater": "Erik spa Heater",
    "switch.erik_spa_economy_mode": "Erik spa Economy mode",
    "sensor.smartbox_effekt_spa": "Smartbox Effekt Spa",                        # EnergyWizards egen utdata
    "sensor.erik_spa_other_status": "Erik spa Status",
    "climate.annat_bad_heater": "Annat bad Heater",                              # ett annat bad: får inte blandas in
    "sensor.annat_bad_current_temperature": "Annat bad Current temperature",
    "switch.annat_bad_economy_mode": "Annat bad Economy mode",
}
# Precis det den automatiska upptäckten skrev åt honom
OLD = {"current_temp": "climate.erik_spa_heater", "power_w": "sensor.smartbox_effekt_spa"}


def test_own_entities_are_recognised():
    assert spa_entities.is_own("sensor.smartbox_effekt_spa") and spa_entities.is_own("sensor.energywizard_kort")
    assert not spa_entities.is_own("sensor.erik_spa_current_temperature") and not spa_entities.is_own("climate.spa_heater")


def test_old_discovery_result_is_completed_from_the_same_device_family():
    done = spa_entities.complete_gecko(OLD, NAMES)
    assert done["climate"] == "climate.erik_spa_heater"
    assert done["current_temp"] == "sensor.erik_spa_current_temperature"      # en riktig sensor i stället för climate-texten
    assert done["target_temp"] == "sensor.erik_spa_target_temperature"
    assert done["water_heater"] == "water_heater.erik_spa_heater"
    assert done["economy_mode"] == "switch.erik_spa_economy_mode"
    assert "power_w" not in done                                              # vår egen sensor är aldrig en källa


def test_another_spa_is_never_mixed_in():
    done = spa_entities.complete_gecko({"climate": "climate.annat_bad_heater"}, NAMES)
    assert done["current_temp"] == "sensor.annat_bad_current_temperature" and done["economy_mode"] == "switch.annat_bad_economy_mode"
    assert all("erik" not in str(v) for v in done.values())


def test_a_users_own_choices_are_never_overwritten():
    mine = {"climate": "climate.erik_spa_heater", "current_temp": "sensor.min_egen_temp", "economy_mode": "switch.min_eco",
            "target_temp": "sensor.min_mal", "water_heater": "water_heater.min_varmare", "power_w": "sensor.min_effekt"}
    assert spa_entities.complete_gecko(mine, NAMES) == mine


def test_only_entities_that_exist_are_used():
    names = {"climate.erik_spa_heater": "Erik spa Heater"}                    # inga syskon i HA
    done = spa_entities.complete_gecko(OLD, names)
    assert done == {"current_temp": "climate.erik_spa_heater", "climate": "climate.erik_spa_heater"}


def test_current_and_target_are_not_confused_and_swedish_names_work():
    names = {"climate.bad_heater": "Bad", "sensor.bad_sensor_1": "Vattentemperatur", "sensor.bad_sensor_2": "Måltemperatur",
             "switch.bad_switch_3": "Ekonomiläge"}
    done = spa_entities.complete_gecko({"climate": "climate.bad_heater"}, names)
    assert done["current_temp"] == "sensor.bad_sensor_1" and done["target_temp"] == "sensor.bad_sensor_2"
    assert done["economy_mode"] == "switch.bad_switch_3"


def test_no_anchor_means_nothing_is_guessed():
    assert spa_entities.complete_gecko({}, NAMES) == {}
    assert spa_entities.complete_gecko({"power_w": "sensor.min_effekt"}, NAMES) == {"power_w": "sensor.min_effekt"}


def test_a_list_of_phase_sensors_loses_only_our_own():
    done = spa_entities.complete_gecko({"climate": "climate.erik_spa_heater", "power_phases": ["sensor.a_fas", "sensor.smartbox_effekt_spa"]}, NAMES)
    assert done["power_phases"] == ["sensor.a_fas"]


# --- upptäckten ---

def _ent(e, n, d="dev_spa", dc=None, u=None, st="0"):
    return {"e": e, "n": n, "a": None, "d": d, "dn": "Gecko in.touch2", "m": "Gecko", "mo": "in.touch2", "dc": dc, "u": u, "st": st}


def _spa_entities():
    return [_ent(e, n, dc=("temperature" if e.startswith("sensor.erik_spa_c") else None)) for e, n in NAMES.items() if "annat" not in e] + [
        _ent("sensor.smartbox_effekt_spa", "Smartbox Effekt Spa", d=None, dc="power", u="W", st="1800")]


def test_discovery_skips_our_own_power_sensor_and_maps_the_whole_spa():
    with patch("discovery._check_configured_heat_pump", return_value=None):
        spa = discovery.discover_house(_spa_entities())["spa"]
    assert spa["power_entity"] is None                                        # förut sensor.smartbox_effekt_spa
    assert spa["driver"] == "gecko"
    assert spa["current_temp_entity"] == "sensor.erik_spa_current_temperature"
    assert spa["entities"] == {"climate": "climate.erik_spa_heater", "current_temp": "sensor.erik_spa_current_temperature",
                               "target_temp": "sensor.erik_spa_target_temperature", "water_heater": "water_heater.erik_spa_heater",
                               "economy_mode": "switch.erik_spa_economy_mode"}


def test_discovery_keeps_the_climate_entity_when_there_are_no_sensors():
    only = [_ent("climate.spa_heater", "Spa Heater", st="heat")]
    with patch("discovery._check_configured_heat_pump", return_value=None):
        spa = discovery.discover_house(only)["spa"]
    assert spa["current_temp_entity"] == "climate.spa_heater" and spa["entities"] == {"climate": "climate.spa_heater"}


def test_no_other_category_can_pick_our_own_entities():
    own = [_ent("sensor.smartbox_effekt_bil", "Smartbox Effekt Bil", d=None, dc="power", u="W"),
           _ent("sensor.energywizard_kort", "EnergyWizard Kort", d=None)]
    with patch("discovery._check_configured_heat_pump", return_value=None):
        found = discovery.discover_house(_spa_entities() + own)
    assert "smartbox" not in str(found) and "energywizard_kort" not in str(found)


# --- den skrivna konfigurationen ---

def _wd():
    mod = sys.modules.get("webdashboard_app")
    if mod is None:
        cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
        try:
            spec = importlib.util.spec_from_file_location("webdashboard_app", ROOT / "webdashboard" / "app.py")
            mod = importlib.util.module_from_spec(spec); sys.modules["webdashboard_app"] = mod; spec.loader.exec_module(mod)
        finally:
            os.chdir(cwd)
    return mod


def test_written_house_config_carries_the_complete_gecko_mapping_and_loads():
    with patch("discovery._check_configured_heat_pump", return_value=None):
        spa = discovery.discover_house(_spa_entities())["spa"]
    cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
    try:
        cfg = yaml.safe_load(_wd()._build_house_config_yaml({"spa": spa}))
    finally:
        os.chdir(cwd)
    ents = cfg["spa"]["entities"]
    assert cfg["spa"]["driver"] == "gecko"
    assert ents == {"climate": "climate.erik_spa_heater", "current_temp": "sensor.erik_spa_current_temperature",
                    "target_temp": "sensor.erik_spa_target_temperature", "water_heater": "water_heater.erik_spa_heater",
                    "economy_mode": "switch.erik_spa_economy_mode"}                # ingen power_w: vår egen sensor
    assert isinstance(house_config.build_spa_driver(cfg), GeckoSpaDriver)


def test_a_climate_entity_is_not_written_as_current_temp_and_own_power_is_never_written():
    spa = {"driver": "gecko", "current_temp_entity": "climate.x_heater", "power_entity": "sensor.smartbox_effekt_spa",
           "entities": {"climate": "climate.x_heater", "current_temp": "climate.x_heater", "bad id; rm -rf": "sensor.a"}}
    cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
    try:
        cfg = yaml.safe_load(_wd()._build_house_config_yaml({"spa": spa}))
    finally:
        os.chdir(cwd)
    assert cfg["spa"]["entities"] == {"climate": "climate.x_heater"}


# --- drivrutinen i hans exakta läge (äldre konfiguration, ingenting omskrivet) ---

class _Posts:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url.rsplit("/services/", 1)[-1], kw.get("json")))
        return type("R", (), {"raise_for_status": lambda s: None})()


def _states(**over):
    s = {
        "climate.erik_spa_heater": {"state": "heat", "attributes": {"friendly_name": "Erik spa Heater", "current_temperature": 36.5, "temperature": 38}},
        "sensor.erik_spa_current_temperature": {"state": "36.4", "attributes": {"friendly_name": "Erik spa Current temperature"}},
        "sensor.erik_spa_target_temperature": {"state": "38.0", "attributes": {"friendly_name": "Erik spa Target temperature"}},
        "water_heater.erik_spa_heater": {"state": "heating", "attributes": {"friendly_name": "Erik spa Heater"}},
        "switch.erik_spa_economy_mode": {"state": "off", "attributes": {"friendly_name": "Erik spa Economy mode"}},
        "sensor.smartbox_effekt_spa": {"state": "1800", "attributes": {"friendly_name": "Smartbox Effekt Spa"}},
    }
    s.update(over)
    return s


def test_driver_reads_temperature_and_target_with_the_old_configuration():
    with patch.object(homeassistant, "_states_cache", _states()), patch.object(homeassistant, "update_states", lambda: None):
        d = GeckoSpaDriver(dict(OLD))
        st = d.read_state()
        assert st["current_temp"] == 36.4 and st["target_temp"] == 38.0 and st["heater_state"] == "heating"
        assert d.read_power_detail()["total_w"] is None                        # vår egen sensor matas inte tillbaka in


def test_driver_falls_back_to_the_climate_attribute_when_there_is_no_sensor():
    only = {"climate.erik_spa_heater": _states()["climate.erik_spa_heater"]}
    with patch.object(homeassistant, "_states_cache", only), patch.object(homeassistant, "update_states", lambda: None):
        st = GeckoSpaDriver(dict(OLD)).read_state()
    assert st["current_temp"] == 36.5 and st["target_temp"] == 38.0           # attributen, inte textens "heat"


def test_driver_controls_target_and_economy_through_the_completed_entities():
    posts = _Posts()
    with patch.object(homeassistant, "_states_cache", _states()), patch.object(homeassistant, "update_states", lambda: None), \
            patch.object(homeassistant.requests, "post", posts):
        d = GeckoSpaDriver(dict(OLD))
        d.set_target_temp(30.0)
        d.set_economy(True)
    assert ("climate/set_temperature", {"entity_id": "climate.erik_spa_heater", "temperature": 30.0}) in posts.calls
    assert ("switch/turn_on", {"entity_id": "switch.erik_spa_economy_mode"}) in posts.calls


def test_driver_never_overrides_what_the_user_configured():
    mine = {"climate": "climate.erik_spa_heater", "current_temp": "sensor.erik_spa_target_temperature", "economy_mode": "switch.erik_spa_economy_mode"}
    with patch.object(homeassistant, "_states_cache", _states()), patch.object(homeassistant, "update_states", lambda: None):
        assert GeckoSpaDriver(dict(mine)).read_state()["current_temp"] == 38.0   # användarens val gäller, hur konstigt det än är


# --- entitets-id:n från webbläsaren kontrolleras linjärt (CodeQL, #574) ---

def test_valid_entity_id_accepts_ids_and_rejects_everything_else():
    for ok in ("sensor.a", "climate.erik_spa_heater", "water_heater.x_1", "switch.erik_spa_economy_mode", "_x.y"):
        assert spa_entities.valid_entity_id(ok), ok
    for bad in ("", "a", "sensor", "sensor.", ".x", "sensor.a.b", "Sensor.x", "sensor.X", "sensor.a b", "sensor.a;b", "sensor.å",
                "1sensor.x", "sensor.a\n", None, 5, ["sensor.a"], "x" * 121 + ".y"):
        assert not spa_entities.valid_entity_id(bad), repr(bad)


def test_a_very_long_hostile_value_is_rejected_at_once():
    import time
    t = time.time()
    for s in ("_" * 200_000, "a" * 200_000 + "!", ("_" * 5000) + ".", "sensor." + "_" * 200_000 + "!"):
        assert not spa_entities.valid_entity_id(s)
    assert time.time() - t < 1.0                                   # linjärt, inte polynomiskt


def test_writer_drops_a_hostile_or_malformed_entity_value():
    spa = {"driver": "gecko", "entities": {"climate": "climate.ok_heater", "water_heater": "water_heater.x: {evil}",
                                            "economy_mode": "switch.a\nspa: hacked", "target_temp": "_" * 50_000}}
    cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
    try:
        text = _wd()._build_house_config_yaml({"spa": spa})
    finally:
        os.chdir(cwd)
    cfg = yaml.safe_load(text)
    assert cfg["spa"]["entities"] == {"climate": "climate.ok_heater"} and "hacked" not in text and "evil" not in text


# --- samma enhet, olika namnstammar (en omdöpt entitet) ---

RENAMED = {
    "climate.spabad_heater": "Spabad Heater",                                    # omdöpt av användaren
    "sensor.spa_xxx_current_temperature": "Spa xxx Current temperature",
    "sensor.spa_xxx_target_temperature": "Spa xxx Target temperature",
    "water_heater.spa_xxx_heater": "Spa xxx Heater",
    "switch.spabad_economy_mode": "Spabad Economy mode",
    "sensor.annat_current_temperature": "Annat Current temperature",            # ett annat bad (annan enhet)
}
DEV = {"climate.spabad_heater": "dev_a", "sensor.spa_xxx_current_temperature": "dev_a", "sensor.spa_xxx_target_temperature": "dev_a",
       "water_heater.spa_xxx_heater": "dev_a", "switch.spabad_economy_mode": "dev_a", "sensor.annat_current_temperature": "dev_b"}


def test_same_device_is_a_sibling_even_when_the_name_stems_differ():
    done = spa_entities.complete_gecko({"climate": "climate.spabad_heater"}, RENAMED, DEV)
    assert done["current_temp"] == "sensor.spa_xxx_current_temperature"
    assert done["target_temp"] == "sensor.spa_xxx_target_temperature" and done["water_heater"] == "water_heater.spa_xxx_heater"
    assert done["economy_mode"] == "switch.spabad_economy_mode"                   # samma stam som climate: hittas av båda vägarna


def test_without_device_ids_only_the_name_stem_is_used():
    done = spa_entities.complete_gecko({"climate": "climate.spabad_heater"}, RENAMED)
    assert done["economy_mode"] == "switch.spabad_economy_mode" and "current_temp" not in done     # sensorerna har en annan stam


def test_another_device_is_never_a_sibling():
    done = spa_entities.complete_gecko({"climate": "climate.spabad_heater"}, RENAMED, DEV)
    assert "annat" not in str(done)


def test_discovery_uses_the_device_for_a_renamed_spa():
    ents = [_ent(e, n, d=DEV[e], dc=("temperature" if "temperature" in e else None)) for e, n in RENAMED.items()]
    with patch("discovery._check_configured_heat_pump", return_value=None):
        spa = discovery.discover_house(ents)["spa"]
    assert spa["entities"]["current_temp"] == "sensor.spa_xxx_current_temperature" and spa["entities"]["economy_mode"] == "switch.spabad_economy_mode"
