"""Del A av Testa ditt system: läsningar av allt som valts i installationen (system_check.py)."""
from datetime import datetime, timedelta, timezone

import system_check as sc

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def S(state, unit=None, age_min=1, **attrs):
    a = dict(attrs)
    if unit:
        a["unit_of_measurement"] = unit
    return {"state": state, "attributes": a, "last_updated": (NOW - timedelta(minutes=age_min)).isoformat()}


CFG = {
    "heat_pump": {"enabled": True, "driver": "ha_entities", "entities": {
        "indoor_temp": "sensor.inne", "outdoor_temp": "sensor.ute", "power_w": ["sensor.p1", "sensor.p2"]}},
    "spa": {"enabled": True, "driver": "gecko", "entities": {"current_temp": "sensor.badtemp", "climate": "climate.bad"}},
    "evs": [{"id": "tesla", "name": "Tesla", "entities": {"soc": "sensor.soc", "wake_button": "button.wake"},
             "charger": {"entities": {"current_a": "sensor.strom", "status": "sensor.status"}}}],
}
STATES = {"sensor.inne": S("21.5", "°C"), "sensor.ute": S("-2.0", "°C"), "sensor.p1": S("1200", "W"), "sensor.p2": S("0.3", "kW"),
          "sensor.badtemp": S("38.5", "°C"), "climate.bad": S("auto", current_temperature=38.5),
          "sensor.soc": S("62", "%"), "button.wake": S("unknown"), "sensor.strom": S("0", "A"), "sensor.status": S("awaiting_start")}


def _g(groups, name):
    return next(g for g in groups if g["device"] == name)


def test_allt_friskt_ger_inga_fel_men_laddbox_utan_effekt_varnas():
    gs = sc.check_entities(CFG, STATES, NOW)
    assert [g["device"] for g in gs][:3] == ["Värmepump", "Spabad", "Tesla"]
    assert _g(gs, "Värmepump")["worst"] == sc.OK and _g(gs, "Tesla")["worst"] == sc.OK        # knappen 'unknown' är normalt
    box = _g(gs, "Laddbox, Tesla")
    assert box["worst"] == sc.WARN and any("0 kr" in i["note"] for i in box["items"])          # #578


def test_saknad_otillganglig_och_icke_numerisk_entitet():
    st = dict(STATES); st.pop("sensor.ute"); st["sensor.inne"] = S("unavailable"); st["sensor.p1"] = S("heat")
    gs = sc.check_entities(CFG, st, NOW)
    notes = {i["label"]: i for i in _g(gs, "Värmepump")["items"]}
    assert notes["Utetemperatur"]["status"] == sc.FAIL and "Finns inte" in notes["Utetemperatur"]["note"]
    assert notes["Innetemperatur"]["status"] == sc.FAIL and "unavailable" in notes["Innetemperatur"]["note"]
    assert any(i["status"] == sc.FAIL and "inte ett tal" in i["note"] for i in _g(gs, "Värmepump")["items"])
    assert _g(gs, "Värmepump")["worst"] == sc.FAIL


def test_orimliga_varden_och_gammal_data_varnas():
    st = dict(STATES); st["sensor.inne"] = S("250", "°C"); st["sensor.ute"] = S("-2.0", "°C", age_min=400); st["sensor.soc"] = S("162", "%")
    gs = sc.check_entities(CFG, st, NOW)
    it = {i["label"]: i for i in _g(gs, "Värmepump")["items"]}
    assert it["Innetemperatur"]["status"] == sc.WARN and "Orimlig" in it["Innetemperatur"]["note"]
    assert it["Utetemperatur"]["status"] == sc.WARN and "uppdaterad" in it["Utetemperatur"]["note"]
    assert any(i["status"] == sc.WARN and "0 till 100" in i["note"] for i in _g(gs, "Tesla")["items"])


def test_climate_entitet_som_temperatur_lases_ur_attribut():
    cfg = {"spa": {"enabled": True, "driver": "gecko", "entities": {"current_temp": "climate.bad"}}}
    gs = sc.check_entities(cfg, {"climate.bad": S("heat", current_temperature=37.0)}, NOW)
    assert _g(gs, "Spabad")["worst"] == sc.OK
    gs = sc.check_entities(cfg, {"climate.bad": S("heat")}, NOW)
    assert _g(gs, "Spabad")["worst"] == sc.WARN


def test_avstangd_sektion_och_saknade_obligatoriska_val():
    cfg = {"heat_pump": {"enabled": False, "entities": {"indoor_temp": "sensor.x"}},
           "spa": {"enabled": True, "driver": "gecko", "entities": {}},
           "battery": {"enabled": True, "driver": "generic", "entities": {}}}
    gs = sc.check_entities(cfg, {}, NOW)
    names = [g["device"] for g in gs]
    assert "Värmepump" not in names
    assert _g(gs, "Spabad")["worst"] == sc.FAIL and _g(gs, "Batteri")["worst"] == sc.FAIL


def test_drivrutinsrader_och_sammanfattning():
    g = sc.driver_rows("Värmepump (drivrutin)", {"indoor_temp": 21.0, "outdoor_temp": None}, [("indoor_temp", "Inne"), ("outdoor_temp", "Ute")])
    assert g["worst"] == sc.WARN and g["items"][0]["status"] == sc.OK
    assert sc.driver_rows("X", None, [])["worst"] == sc.FAIL
    s = sc.summarize([g])
    assert "2 läsningar" in s and "1 fungerar" in s and "1 varningar" in s
    assert sc.summarize([]) == "Inga entiteter att kontrollera."
