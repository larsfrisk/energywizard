"""sensor.energywizard_kort (smartbox/ha_card_feed.py): korten i HA ritar ur den här sensorns attribut."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import ha_card_feed

NOW = datetime(2026, 11, 20, 14, 30, tzinfo=timezone(timedelta(hours=1)))


def _slot(minutes, price, heat="EXPENSIVE", ev=None, sun=0):
    t = (NOW.replace(hour=14, minute=0) + timedelta(minutes=minutes)).isoformat()
    return {"t": t, "spot": price - 0.6, "price": price, "bat": None, "bat_kw": None, "soc": None, "bat_balance": False,
            "ev": ev or {}, "heat": heat, "sun_w": sun}


FLOW = {"nodes": [
    {"key": "sol", "label": "Sol", "icon": "☀️", "w": 47.4, "active": False, "detail": "0.0 kW", "page": "x", "role": "source"},
    {"key": "nat", "label": "Elnät", "icon": "🔌", "w": 8212, "active": True, "detail": "Köper 8.2 kW", "page": "x", "role": "grid"},
    {"key": "ev_nissan", "label": "Nissan Leaf", "icon": "🚗", "w": None, "active": False, "detail": "Laddar inte · 64 %", "role": "load"}],
    "why": {"ev_nissan": "x" * 500}}
PC = {"ok": True, "now": NOW.isoformat(), "has_battery": False, "cars": [{"id": "nissan", "name": "Nissan Leaf"}],
      "slots": [_slot(0, 2.5), _slot(15, 2.6, "CHEAP", {"nissan": 3.7}, sun=1200), _slot(30, 1.1, "CHEAP"), _slot(45, 1.0, "CHEAP")]}


def test_tillstand_och_pris_ur_pagaende_kvart():
    state, a = ha_card_feed.build(FLOW, PC, now=NOW, unit="kr")
    assert a["price"] == {"now": 1.1, "spot": 0.5, "mode": "C"} and state == "billigt"      # 14:30-kvarten pågår
    assert a["v"] == 1 and a["unit"] == "kr" and a["battery"] is False


def test_flodet_blir_korta_poster_med_hela_watt():
    _, a = ha_card_feed.build(FLOW, PC, now=NOW)
    assert a["flow"][0] == {"k": "sol", "l": "Sol", "i": "☀️", "w": 47, "on": False, "d": "0.0 kW", "r": "source"}
    assert a["flow"][2]["w"] is None and a["flow"][1]["on"] is True
    assert len(a["why"]["ev_nissan"]) == 240                       # förklaringen kortas


def test_planen_en_rad_per_kvart_med_elbil_summerad():
    _, a = ha_card_feed.build(FLOW, PC, now=NOW)
    assert len(a["slots"]) == 4 and a["slots"][1][3] == "C" and a["slots"][1][5] == 3.7 and a["slots"][1][4] == 1200
    assert a["slots"][0][3] == "E" and a["slots"][0][5] == 0


def test_tom_data_kraschar_inte():
    state, a = ha_card_feed.build({}, {}, now=NOW)
    assert state == "okänt" and a["flow"] == [] and a["slots"] == [] and a["price"]["now"] is None


def test_attributen_ryms_i_havets_grans_med_en_hel_dag():
    pc = {"ok": True, "has_battery": True, "cars": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
          "slots": [_slot(15 * i, 2.0 + i / 100, "CHEAP" if i % 2 else "EXPENSIVE", {"a": 3.7, "b": 1.4}, sun=900) for i in range(96)]}
    _, a = ha_card_feed.build(FLOW, pc, now=NOW)
    assert len(json.dumps(a, ensure_ascii=False)) < 16000
