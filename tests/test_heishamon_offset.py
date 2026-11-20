"""#491: HeishaMon-drivrutinen i FTW skrev safe_offset (0) till Z1_Heat_Request_Temp vid varje
vakthund och omstart. Den som styr förskjutningen från Home Assistant fick den nollställd.
Upstream rättade vakthunden (0.8.1: återställer bara efter att FTW själv skrivit). Vår enda ändring ovanpå är
control: false (helt läsande). Ingen MQTT-anslutning: publiceringen fångas i minnet.
Värden nil betyder lyckad publicering, samma kontrakt som FTW:s värd (felsträng vid misslyckande)."""
import os

import pytest

pytest.importorskip("lupa")
from lua_host import LuaDriver, FTW_DIR  # noqa: E402

TOPIC = "panasonic_heat_pump/set/Z1_Heat_Request_Temp"


@pytest.fixture
def published(monkeypatch):
    sent = []

    def publish(self, topic, payload):
        sent.append((str(topic), str(payload)))
        return None

    monkeypatch.setattr(LuaDriver, "_mqtt_subscribe", lambda self, topic: None)
    monkeypatch.setattr(LuaDriver, "_mqtt_publish", publish)
    return sent


def load(config=None):
    return LuaDriver(
        os.path.join(FTW_DIR, "heishamon.lua"),
        host="192.0.2.1",
        port=1883,
        config=config or {},
        allow_write=True,
        log=lambda *_: None,
    )


def test_vakthund_skriver_inte_innan_drivrutinen_själv_styrt(published):
    d = load()
    d.L.globals().driver_default_mode()
    d.L.globals().driver_cleanup()
    assert published == []


def test_återställning_efter_egen_skrivning(published):
    d = load()
    assert d.command("set_heat_curve_offset", 0, {"value": 2}) is True
    assert published == [(TOPIC, "2")]
    d.L.globals().driver_default_mode()
    d.L.globals().driver_cleanup()
    assert published == [(TOPIC, "2"), (TOPIC, "0")]      # återställs en gång; markeringen släpps efter lyckad återställning


def test_misslyckad_skrivning_armerar_aterstallning_som_upstream(published, monkeypatch):
    """Upstream (srcfl/device-drivers#235, 0.8.1) markerar före publiceringen: ett misslyckat publicerat kan ändå ha nått
    mäklaren, och en onödig återställning är det gamla, säkra beteendet."""
    def fail(self, topic, payload):
        published.append((str(topic), str(payload)))
        return "broker nere"

    monkeypatch.setattr(LuaDriver, "_mqtt_publish", fail)
    d = load()
    assert d.command("set_heat_curve_offset", 0, {"offset": 1}) is False
    published.clear()
    d.L.globals().driver_default_mode()
    assert published == [(TOPIC, "0")]


def test_control_false_skriver_aldrig_men_läser_ändå(published):
    d = load({"control": False})
    assert list(d.L.globals().DRIVER.controls) == []
    assert d.command("set_heat_curve_offset", 0, {"value": 2}) is False
    d.L.globals().driver_default_mode()
    d.L.globals().driver_cleanup()
    assert published == []
    d._mqtt_buf.append({
        "topic": "panasonic_heat_pump/main/Z1_Heat_Request_Temp",
        "payload": "2",
        "received_at": 1,
    })
    d.poll()
    assert d.metrics["hp_z1_heat_offset"] == (2, "°C")
    assert published == []


def test_control_som_strängen_false(published):
    d = load({"control": "false"})
    assert d.command("set_heat_curve_offset", 0, {"value": -2}) is False
    assert published == []


def test_för_hög_förskjutning_klampas(published):
    d = load()
    assert d.command("set_heat_curve_offset", 0, {"value": 9}) is True
    assert published == [(TOPIC, "3")]
