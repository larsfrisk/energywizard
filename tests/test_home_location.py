"""Hemmets position (2026-11-15): var hårdkodad för alla installationer och låg 1,77 km från Emils hemzon. Hämtas nu ur
inställning eller Home Assistants zone.home."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))


def test_zone_home_används(monkeypatch):
    import homeassistant
    import weather
    monkeypatch.delenv("HOME_LATITUDE", raising=False)
    monkeypatch.delenv("HOME_LONGITUDE", raising=False)
    zon = {"latitude": -33.87, "longitude": 151.21}
    monkeypatch.setattr(homeassistant, "_get_numeric_attribute", lambda e, a: zon[a] if e == "zone.home" else None)
    import ew_settings
    monkeypatch.setattr(ew_settings, "get", lambda k, d=None: None)
    assert weather.refresh_location() == (-33.87, 151.21)
    assert "latitude=-33.87" in weather.open_meteo_url() and "longitude=151.21" in weather.open_meteo_url()


def test_inställning_går_före_zonen(monkeypatch):
    import homeassistant
    import weather
    monkeypatch.setenv("HOME_LATITUDE", "59.33")
    monkeypatch.setenv("HOME_LONGITUDE", "18.07")
    monkeypatch.setattr(homeassistant, "_get_numeric_attribute", lambda e, a: 1.0)
    assert weather.refresh_location() == (59.33, 18.07)
