"""#577: generic_climate läste bara climate-entiteten och ignorerade ute-, framlednings-, retur-, varmvatten- och effektgivare."""
from unittest.mock import patch

import homeassistant
from drivers.heatpump_generic import GenericClimateHeatPumpDriver

ENT = {"climate": "climate.bvp", "outdoor_temp": "sensor.ute", "forward_temp": "sensor.fram", "return_temp": "sensor.retur",
       "water_temp": "sensor.vv", "room_target": "climate.bvp", "power_w": ["sensor.p_varme", "sensor.p_vv"]}
VAL = {"sensor.ute": 2.5, "sensor.fram": 35.0, "sensor.retur": 30.5, "sensor.vv": 48.0, "sensor.p_varme": 1.2, "sensor.p_vv": 300.0}
UNIT = {"sensor.p_varme": "kW", "sensor.p_vv": "W"}


def _run(entities):
    drv = GenericClimateHeatPumpDriver(entity_id="climate.bvp", entities=entities)
    cache = {k: {"attributes": {"unit_of_measurement": u}} for k, u in UNIT.items()}
    with patch.object(homeassistant, "_get_numeric_state", lambda e: VAL.get(e)), \
         patch.object(homeassistant, "_get_numeric_attribute", lambda e, a: 21.0), \
         patch.object(homeassistant, "_get_raw_state", lambda e: "heat"), \
         patch.object(homeassistant, "_states_cache", cache):
        return drv.read_sensors()


def test_extra_givare_och_summerad_effekt_lases():
    r = _run(ENT)
    assert (r["outdoor_temp"], r["forward_temp"], r["return_temp"], r["water_temp"]) == (2.5, 35.0, 30.5, 48.0)
    assert r["indoor_temp"] == 21.0 and r["compressor_power_w"] == 1500.0          # 1,2 kW + 300 W


def test_utan_extra_entiteter_som_forut():
    r = _run({"climate": "climate.bvp"})
    assert r["outdoor_temp"] is None and "compressor_power_w" not in r and r["indoor_temp"] == 21.0


def test_saknad_givare_ger_none_inte_krasch():
    VAL_BAK = dict(VAL); VAL.pop("sensor.fram")
    try:
        assert _run(ENT)["forward_temp"] is None
    finally:
        VAL.update(VAL_BAK)
