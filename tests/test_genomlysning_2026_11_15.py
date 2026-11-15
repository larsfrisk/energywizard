"""Genomlysningen 2026-11-15: resplanen i appen (knappen fanns, funktionen saknades), varmvattenvanorna som lästes om
varje minut, och prisformen som frågades om vid tom databas."""
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import pandas as pd
import learning
import trip_plan

SWE = ZoneInfo("Europe/Stockholm")


def test_appens_resplan_finns():
    js = open(os.path.join(ROOT, "ewapp", "static", "app.js"), encoding="utf-8").read()
    assert 'if (a === "trip") return tripSheet(c);' in js
    assert re.search(r"function tripSheet\(", js)


def test_resplan_tolkas_och_går_ut():
    nu = datetime(2026, 11, 15, 20, 0, tzinfo=SWE)
    when = trip_plan.make(nu, 1, "07:30", 80)
    assert when == datetime(2026, 11, 16, 7, 30, tzinfo=SWE)
    assert trip_plan.parse(trip_plan.encode(when, 80), nu) == (when, 80)
    assert trip_plan.parse(trip_plan.encode(when, 80), when + timedelta(minutes=1)) is None
    assert trip_plan.make(nu, 0, "07:30", 80).day == 16           # passerat klockslag idag -> imorgon
    assert trip_plan.parse("", nu) is None and trip_plan.parse("skräp|x", nu) is None


def test_motorn_använder_resplanen_som_klar_senast():
    src = open(os.path.join(ROOT, "smartbox", "main.py"), encoding="utf-8").read()
    assert 'trip_plan.parse(all_overrides.get(f"{_c}_trip"), now)' in src


def test_varmvattenvanor_läses_inte_om_varje_minut(monkeypatch):
    calls = []
    monkeypatch.setattr(learning, "_hot_water_habit_compute", lambda: calls.append(1) or {(0, 7): 0.5})
    monkeypatch.setattr(learning, "_hw_habit_cache", None, raising=False)
    monkeypatch.setattr(learning, "_too_little_data_at", {}, raising=False)
    for _ in range(5):
        assert learning.get_hot_water_habit_profile() == {(0, 7): 0.5}
    assert len(calls) == 1


def test_prisformen_frågas_inte_om_vid_tom_databas(monkeypatch):
    from contextlib import contextmanager
    calls = []

    @contextmanager
    def db():
        yield None
    monkeypatch.setattr(learning.sm_logger, "get_db", db)
    monkeypatch.setattr(learning.pd, "read_sql", lambda *a, **k: calls.append(1) or pd.DataFrame())
    monkeypatch.setattr(learning, "_price_shape_cache", None, raising=False)
    monkeypatch.setattr(learning, "_too_little_data_at", {}, raising=False)
    for _ in range(5):
        assert learning.get_price_shape_profile() == {}
    assert len(calls) == 1
