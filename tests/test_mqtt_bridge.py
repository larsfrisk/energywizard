"""MQTT med autodiscovery (mqtt_bridge.py): samma entitets-id som REST-sensorerna, en enhet "EnergyWizard",
tillgänglighet, och två brytare från HA."""
import json

import mqtt_bridge


def test_discovery_behaller_entitets_id_och_enhet():
    topic, p = mqtt_bridge.discovery_payload("sensor.smartbox_prisprognos",
                                             {"friendly_name": "Smartbox Prisprognos", "unit_of_measurement": "kr/kWh", "icon": "mdi:chart-bar", "idag": [1]})
    assert topic == "homeassistant/sensor/energywizard/smartbox_prisprognos/config"
    assert p["name"] == "Prisprognos" and p["unique_id"] == "energywizard_smartbox_prisprognos"
    assert p["default_entity_id"] == "sensor.smartbox_prisprognos" and p["object_id"] == "smartbox_prisprognos"
    assert p["unit_of_measurement"] == "kr/kWh" and p["availability_topic"] == "energywizard/status"
    assert p["device"]["identifiers"] == ["energywizard"] and "idag" not in p
    json.dumps(p)


def test_binar_sensor_och_brytare():
    _, p = mqtt_bridge.discovery_payload("binary_sensor.smartbox_elbil_laddar_fran_natet", {"friendly_name": "Elbil laddar"})
    assert p["payload_on"] == "on"
    topic, s = mqtt_bridge.switch_payload("shadow_mode")
    assert topic.startswith("homeassistant/switch/energywizard/") and s["command_topic"] == "energywizard/switch/shadow_mode/set"


def test_av_utan_broker(monkeypatch, tmp_path):
    import ew_settings
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "ew.json"))
    ew_settings._cache.update(mtime=None, data={})
    monkeypatch.delenv("MQTT_HOST", raising=False)
    assert mqtt_bridge.config() is None
    assert mqtt_bridge.publish({"sensor.smartbox_puls": ("x", {})}) is False      # ha_publisher använder REST
    ew_settings.update(mqtt_host="192.168.1.10", mqtt_user="ew")
    assert mqtt_bridge.config() == {"host": "192.168.1.10", "port": 1883, "user": "ew", "password": None}


def test_alla_id_ar_ascii():
    for key in mqtt_bridge.SWITCHES:
        _, s = mqtt_bridge.switch_payload(key)
        assert s["default_entity_id"].isascii() and s["command_topic"].isascii()


def test_bilens_laddlage_som_vaeljare_i_ha():
    """#557: varje bil får en väljare (Auto, Ladda nu, Pausa) som Bil-kortet visar som knappar."""
    topic, p = mqtt_bridge.car_select_payload("nissan", "Nissan Leaf")
    assert topic == "homeassistant/select/energywizard/energywizard_ev_nissan_mode/config"
    assert p["options"] == ["Auto", "Ladda nu", "Pausa"] and p["default_entity_id"] == "select.energywizard_ev_nissan_mode"
    assert p["command_topic"] == "energywizard/select/ev_nissan/set" and p["state_topic"] == "energywizard/select/ev_nissan/state"
    json.dumps(p)


def test_laddlage_ur_overstyrningarna():
    assert mqtt_bridge.car_mode("tesla", {}) == "Auto"
    assert mqtt_bridge.car_mode("tesla", {"tesla_force_amps": "16"}) == "Ladda nu"
    assert mqtt_bridge.car_mode("tesla", {"tesla_hold": "on"}) == "Pausa"
    assert mqtt_bridge.car_mode("tesla", {"tesla_hold": "on", "tesla_force_amps": "16"}) == "Ladda nu"     # tvång går före spärr


def test_knapparna_sätter_samma_overstyrningar_som_appen():
    got = {}
    assert mqtt_bridge.apply_car_mode("tesla", "Ladda nu", 16, got.__setitem__) is True
    assert got["tesla_force_amps"] == "16" and got["tesla_hold"] == "off" and got["tesla_charge_now_target"] == ""
    got.clear()
    assert mqtt_bridge.apply_car_mode("tesla", "Pausa", 16, got.__setitem__) and got["tesla_hold"] == "on" and got["tesla_force_amps"] == "0"
    got.clear()
    assert mqtt_bridge.apply_car_mode("tesla", "Auto", 16, got.__setitem__)
    assert got["tesla_hold"] == "off" and got["tesla_force_amps"] == "0" and got["force_ev_recalc"] == "true"
    got.clear()
    assert mqtt_bridge.apply_car_mode("tesla", "Köp en ny bil", 16, got.__setitem__) is False and got == {}      # okänt: ingenting ändras
