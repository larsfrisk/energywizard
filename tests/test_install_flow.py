"""Enkel installation: HA-adress som http/https, omstart när house_config.yaml ändras, och
entitetsväljarens "Spara och starta" (bara när install.sh gjort filen skrivbar, bara ägaren)."""
import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))

import config_watch  # noqa: E402
import homeassistant  # noqa: E402


@pytest.mark.parametrize("given,expected", [
    ("192.168.1.10", "http://192.168.1.10:8123"),
    ("homeassistant.local:8124/", "http://homeassistant.local:8124"),
    ("http://10.0.0.2:8123/api", "http://10.0.0.2:8123"),
    ("https://ha.example.se", "https://ha.example.se"),        # bakom proxy på 443: rörs inte
    ("https://ha.example.se:8123/", "https://ha.example.se:8123"),
])
def test_normalize_ha_url(given, expected):
    assert homeassistant.normalize_ha_url(given) == expected


def test_config_watch_sees_change(tmp_path):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "a"\n')
    before = config_watch._signature(str(p))
    assert config_watch.changed(str(p), before) is None
    time.sleep(0.01)
    with open(p, "w") as f:                       # på plats, som webben skriver
        f.write('house_id: "a"\nfuse:\n  main_fuse_a: 20\n')
    assert config_watch.changed(str(p), before) is not None
    p.unlink()
    assert config_watch.changed(str(p), before) is None   # borttagen fil -> ingen omstart


def test_config_watch_thread_calls_on_change(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("a\n")
    hits = []
    config_watch.start(str(p), on_change=lambda: hits.append(1), every_s=0.05)
    time.sleep(0.1)
    p.write_text("abc\n")
    for _ in range(60):
        if hits:
            break
        time.sleep(0.1)
    assert hits == [1]


class _FakeRequest:
    def __init__(self, body=None, cookies=None):
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.client = type("c", (), {"host": "10.0.0.5"})()

    async def json(self):
        return self._body


@pytest.fixture(scope="module")
def wd():
    mp = pytest.MonkeyPatch()
    mp.setenv("DASHBOARD_PASSWORD", "hemligt123")
    import webauth
    mp.setattr(webauth, "PASSWORD", "hemligt123")
    cwd = Path.cwd()
    os.chdir(ROOT / "webdashboard")
    try:
        spec = importlib.util.spec_from_file_location("webdashboard_app_install", ROOT / "webdashboard" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["webdashboard_app_install"] = mod
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    yield mod
    mp.undo()


def _cookie(wd, role="owner"):
    return {wd.AUTH.cookie: wd.AUTH.sign(int(time.time()) + 3600, role, role)}


SEL = {"cars": [], "heat_pump": None, "solar": None, "spa": None, "battery": None}


def test_save_refused_without_installer_flag(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.delenv("HOUSE_CONFIG_WRITABLE", raising=False)
    st = asyncio.run(wd.api_house_config_status(_FakeRequest(cookies=_cookie(wd))))
    assert st == {"writable": False}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert r.status_code == 409
    assert p.read_text() == 'house_id: "mitt"\n'          # handskriven config rörs aldrig


def test_save_only_for_owner(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd, "guest"))))
    assert r.status_code == 403
    assert p.read_text() == 'house_id: "mitt"\n'


def test_save_writes_in_place(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    inode = p.stat().st_ino
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    st = asyncio.run(wd.api_house_config_status(_FakeRequest(cookies=_cookie(wd))))
    assert st == {"writable": True}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert r["ok"] is True
    text = p.read_text()
    assert "main_fuse_a" in text
    assert p.stat().st_ino == inode                       # samma fil: Docker-monteringen ser ändringen
    import house_config
    house_config.load_house_config(str(p))                # och motorn kan läsa den


def test_setup_save_preserves_manual_configuration(wd, tmp_path, monkeypatch):
    import yaml
    original = {"house_id": "my-house", "loads": [{"id": "oven", "power_w": 2200}],
                "fuse": {"main_fuse_a": 16, "custom_limit": 12},
                "battery": {"enabled": True, "driver": "generic", "capacity_kwh": 24,
                            "reserve_soc": 35, "control": "av", "normal_max_soc": 85,
                            "entities": {"soc": "sensor.old", "manual": "sensor.custom"}},
                "extensions": {"nested": [1, 2]}}
    p = tmp_path / "house_config.yaml"
    p.write_text(yaml.safe_dump(original), encoding="utf-8")
    inode = p.stat().st_ino
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    selected = {**SEL, "battery": {"driver": "generic", "soc_entity": "sensor.new"}}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(selected, _cookie(wd))))
    assert r["ok"] is True
    saved = yaml.safe_load(p.read_text())
    for key in ("house_id", "loads", "fuse", "extensions"):
        assert saved[key] == original[key]
    for key in ("capacity_kwh", "reserve_soc", "control", "normal_max_soc"):
        assert saved["battery"][key] == original["battery"][key]
    assert saved["battery"]["entities"] == {"soc": "sensor.new", "manual": "sensor.custom"}
    assert p.stat().st_ino == inode


@pytest.mark.parametrize("text", ["loads: [broken", "- not-a-mapping"])
def test_setup_save_refuses_invalid_existing_file(wd, tmp_path, monkeypatch, text):
    p = tmp_path / "house_config.yaml"
    p.write_text(text)
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    result = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert result.status_code == 409
    assert p.read_text() == text


def test_setup_merge_updates_car_fields_and_replaces_changed_driver():
    import house_config
    existing = {"evs": [{"id": "car", "battery_kwh": 75, "manual": True,
                         "charger": {"phases": 1, "max_a": 10}}, {"id": "removed"}],
                "battery": {"driver": "old", "host": "old-device", "modes": {"charge": "old-command"}}}
    new = {"evs": [{"id": "car", "battery_kwh": 60, "charger": {"id": "selected"}}],
           "battery": {"driver": "generic", "enabled": True}}
    merged = house_config.merge_setup_config(existing, new)
    assert merged["evs"] == [{"id": "car", "battery_kwh": 60, "manual": True,
                              "charger": {"phases": 1, "max_a": 10, "id": "selected"}}]
    assert merged["battery"] == new["battery"]
    assert existing["battery"]["host"] == "old-device"
