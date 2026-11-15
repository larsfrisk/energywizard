"""#404: värmepump via Home Assistant-entiteter (t.ex. IVT via Husdata/MQTT) kan ange effektgivare för pumpens el -
en eller flera (värme och varmvatten var för sig) som summeras. Annars uppskattas eleffekten som förut."""
from unittest.mock import patch

import energy_balance
from drivers.heatpump_ha_entities import HaEntitiesHeatPumpDriver

STATES = {"sensor.heating_power": {"state": "1850", "attributes": {"unit_of_measurement": "W"}},
          "sensor.varmvatten_effekt": {"state": "0.4", "attributes": {"unit_of_measurement": "kW"}},
          "sensor.ute": {"state": "3", "attributes": {}}}


def _num(e):
    try:
        return float(STATES[e]["state"])
    except (KeyError, ValueError):
        return None


def drv(power):
    return HaEntitiesHeatPumpDriver({"outdoor_temp": "sensor.ute", "power_w": power})


def test_flera_givare_summeras_med_enhet():
    with patch("homeassistant._get_numeric_state", side_effect=_num), patch("homeassistant._states_cache", STATES):
        out = drv(["sensor.heating_power", "sensor.varmvatten_effekt"]).read_sensors()
    assert out["compressor_power_w"] == 2250.0
    assert energy_balance.pump_el_w(out, lambda f: 9999) == 2250.0      # uppmätt går före uppskattning


def test_en_givare_som_text():
    with patch("homeassistant._get_numeric_state", side_effect=_num), patch("homeassistant._states_cache", STATES):
        assert drv("sensor.heating_power").read_sensors()["compressor_power_w"] == 1850.0


def test_utan_givare_som_förut():
    with patch("homeassistant._get_numeric_state", side_effect=_num), patch("homeassistant._states_cache", STATES):
        out = HaEntitiesHeatPumpDriver({"outdoor_temp": "sensor.ute"}).read_sensors()
    assert out["compressor_power_w"] is None


def test_givare_som_inte_svarar():
    with patch("homeassistant._get_numeric_state", return_value=None), patch("homeassistant._states_cache", {}):
        assert drv("sensor.saknas").read_sensors()["compressor_power_w"] is None
