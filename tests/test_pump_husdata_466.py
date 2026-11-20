"""#466: lärdomar av husdata-h66-modbus - ej inkopplad givare, registerkarta ur H66:ans startsida, en klient åt gången,
omförsök vid kollision och kontroll av skrivvärden. Fixturen är H66:ans riktiga startsida (Thermia Diplomat, firmware
360301), avläst 2026-11-20."""
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymodbus.exceptions import ModbusIOException

import pump

PAGE = (Path(__file__).parent / "fixtures" / "husdata_h66_home_thermia_diplomat.html").read_text(encoding="utf-8")


def _regs(**over):
    r = [0] * 40
    r[0:13] = [340, 420, 20, 65516, 65526, 200, 600, 760, 65136, 65397, 360, 520, 420]   # riktig avläsning
    for k, v in over.items():
        r[int(k[1:])] = v
    return r


def _client(input_regs):
    c = Mock()
    c.read_input_registers.return_value = SimpleNamespace(isError=lambda: False, registers=input_regs)
    c.read_holding_registers.return_value = SimpleNamespace(isError=lambda: False, registers=[600, 10, 180, 20, 400, 550, 170, 350, 180, 0, 20])
    return c


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(pump, "PUMP_IPS", ["h66.test"])
    monkeypatch.setattr(pump, "_active_ip_index", 0)
    monkeypatch.setattr(pump, "_map_checked", {"h66.test"})          # inget nätanrop mot h66.test
    monkeypatch.setattr(pump, "_RETRY_PAUSE_S", 0)
    monkeypatch.setattr(pump, "_limits_cache", {"at": time.time(), "ip": "h66.test", "limits": {}})


# --- 1. ej inkopplad givare ---

def test_missing_sensor_reads_none_not_minus_40(monkeypatch):
    """Uppmätt på riktiga pumpen: Cooling-givaren som saknas ger råvärde 65136 = -40,0 °C."""
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs()))
    d = pump.read_sensors()
    assert d["cooling_temp"] is None
    assert d["brine_out_temp"] == -2.0 and d["outdoor_temp"] == -1.0 and d["forward_temp"] == 42.0


def test_minus_40_outdoors_is_allowed_but_minus_48_3_is_not(monkeypatch):
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs(i4=65136)))      # -40,0 ute: kan hända i norr
    assert pump.read_sensors()["outdoor_temp"] == -40.0
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs(i4=65053, i3=65053)))   # -48,3 = saknad givare
    d = pump.read_sensors()
    assert d["outdoor_temp"] is None and d["brine_out_temp"] is None


def test_missing_brine_sensor_does_not_trigger_the_freeze_failsafe(monkeypatch):
    """gpm larmar vid brine_out <= -7 °C; en saknad givare får inte se ut som -40."""
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs(i3=65136)))
    assert pump.read_sensors()["brine_out_temp"] is None


# --- 2. registerkartan ur startsidan ---

def test_parse_real_home_page():
    page = pump.parse_home_page(PAGE)
    assert page["controller"] == "Thermia Diplomat" and page["firmware"] == "360301"
    assert page["registers"][4]["name"] == "Outdoor" and page["registers"][4]["kind"] == "Input"
    assert page["registers"][15]["range"] == (10.0, 29.0) and page["registers"][13]["range"] == (30.0, 65.0)
    assert pump.check_register_map(page) == []


def test_other_controller_map_is_detected():
    rego = PAGE.replace("Brine in/Evaporator", "Heat carrier return").replace(">Outdoor<", ">Heat fluid out<")
    bad = pump.check_register_map(pump.parse_home_page(rego))
    assert any("register 2" in b for b in bad) and any("register 4" in b for b in bad)
    assert pump.check_register_map({"registers": {}})            # tom sida = kan inte kontrolleras


def test_register_map_check_is_logged_once(monkeypatch, capsys):
    monkeypatch.setattr(pump, "_map_checked", set())
    calls = []
    monkeypatch.setattr(pump, "fetch_home_page", lambda ip: calls.append(ip) or pump.parse_home_page(PAGE))
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs()))
    pump.read_sensors(); pump.read_sensors()
    assert calls == ["h66.test"] and "registerkartan stämmer" in capsys.readouterr().out


def test_wrong_map_is_warned_not_fatal(monkeypatch, capsys):
    monkeypatch.setattr(pump, "_map_checked", set())
    rego = PAGE.replace("Thermia Diplomat", "Rego 600").replace("Brine in/Evaporator", "Heat carrier return")
    monkeypatch.setattr(pump, "fetch_home_page", lambda ip: pump.parse_home_page(rego))
    monkeypatch.setattr(pump, "_get_client", lambda: _client(_regs()))
    assert pump.read_sensors() is not None
    assert "annan registerkarta" in capsys.readouterr().out


# --- 3. en klient åt gången, omförsök ---

def test_modbus_traffic_is_serialized_between_threads(monkeypatch):
    inside, peak, lock = [0], [0], threading.Lock()

    def slow_read(**kw):
        with lock:
            inside[0] += 1; peak[0] = max(peak[0], inside[0])
        time.sleep(0.05)
        with lock:
            inside[0] -= 1
        return SimpleNamespace(isError=lambda: False, registers=_regs())

    def make():
        c = _client(_regs()); c.read_input_registers.side_effect = slow_read; return c
    monkeypatch.setattr(pump, "_get_client", make)
    ts = [threading.Thread(target=pump.read_sensors) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert peak[0] == 1


def test_one_retry_after_a_dropped_connection(monkeypatch):
    first, second = _client(_regs()), _client(_regs())
    first.read_input_registers.side_effect = ModbusIOException("no response")
    clients = iter([first, second])
    monkeypatch.setattr(pump, "_get_client", lambda: next(clients))
    assert pump.read_sensors() is not None


def test_no_retry_when_gateway_is_down(monkeypatch):
    n = []
    monkeypatch.setattr(pump, "_get_client", lambda: n.append(1))
    assert pump.read_sensors() is None and n == [1]


def test_only_one_retry(monkeypatch):
    n = []

    def bad():
        n.append(1); c = _client(_regs()); c.read_input_registers.side_effect = ModbusIOException("x"); return c
    monkeypatch.setattr(pump, "_get_client", bad)
    assert pump.read_sensors() is None and len(n) == 2


# --- 6. skrivvärden ---

@pytest.mark.parametrize("fn,arg", [(pump.set_room_temp, 990), (pump.set_room_temp, 0), (pump.set_water_stop_temp, 99.0),
                                    (pump.set_water_start_temp, 5.0), (pump.set_operating_mode, 9),
                                    (pump.set_room_temp, float("nan")), (pump.set_room_temp, "x")])
def test_out_of_range_writes_never_reach_the_pump(monkeypatch, fn, arg):
    c = Mock()
    monkeypatch.setattr(pump, "_get_client", lambda: c)
    monkeypatch.setattr("shadow.active", lambda: False)
    assert fn(arg) is False
    assert not c.write_register.called


def test_in_range_write_goes_through(monkeypatch):
    c = Mock(); c.write_register.return_value = SimpleNamespace(isError=lambda: False)
    monkeypatch.setattr(pump, "_get_client", lambda: c)
    monkeypatch.setattr("shadow.active", lambda: False)
    assert pump.set_room_temp(180) is True
    assert c.write_register.call_args.kwargs["value"] == 180 and c.write_register.call_args.kwargs["address"] == 15


def test_limits_come_from_the_pump_page(monkeypatch):
    monkeypatch.setattr(pump, "_limits_cache", {"at": 0.0, "ip": None, "limits": {}})
    monkeypatch.setattr(pump, "fetch_home_page", lambda ip: pump.parse_home_page(PAGE))
    assert pump._live_limits()[15] == (100, 290)
    assert pump._live_limits()[22] == (-50, 50)
    assert pump._write_value_ok(15, 290) and not pump._write_value_ok(15, 291)


def test_unreadable_page_falls_back_to_the_built_in_limits(monkeypatch):
    monkeypatch.setattr(pump, "_limits_cache", {"at": 0.0, "ip": None, "limits": {}})
    monkeypatch.setattr(pump, "fetch_home_page", lambda ip: None)
    assert pump._write_value_ok(15, 180) and not pump._write_value_ok(15, 300)


# --- 5. register som aldrig skrivs ---

def test_engine_never_writes_external_control_or_other_risky_registers():
    import re
    src = (Path(pump.__file__)).read_text(encoding="utf-8")
    written = {int(m) for m in re.findall(r"_write_holding\((\d+)", src)}
    assert written <= {13, 14, 15, 16, 17, 18, 19, 20}, written       # inte 23 (External control, oförutsägbar)
