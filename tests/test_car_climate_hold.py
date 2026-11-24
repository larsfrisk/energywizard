"""#598: håll bilen varm en vald tid efter sluttiden."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))
import car_climate_schedule as cc

TZ = ZoneInfo("Europe/Stockholm")


def at(h, m, day=24):
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


def step(state, now, c_state="off", c_temp=15.0, conn=True, away=False, hold=45):
    return cc.hold_step(state, now, "06:45", hold, 21.0, c_state, c_temp, conn, away)


def test_normalize_hålltid():
    assert cc.normalize(True, "06:45", 21, 45)["hold_min"] == 45
    assert cc.normalize(True, "06:45", 21)["hold_min"] == 0
    assert cc.normalize(True, "06:45", 21, 47)["hold_min"] == 45          # hela 5 minuter
    for bad in (-5, 361, "x"):
        with pytest.raises(ValueError):
            cc.normalize(True, "06:45", 21, bad)


def test_fönstret_gäller_bara_efter_tiden_och_hold_min():
    assert cc.hold_window(at(6, 44), "06:45", 45) is None
    assert cc.hold_window(at(6, 46), "06:45", 45) == at(6, 45)
    assert cc.hold_window(at(7, 29), "06:45", 45) == at(6, 45)
    assert cc.hold_window(at(7, 30), "06:45", 45) is None
    assert cc.hold_window(at(7, 0), "06:45", 0) is None


def test_hålltid_över_midnatt():
    assert cc.hold_window(at(0, 30, day=25), "23:30", 120) == at(23, 30, day=24)


def test_värmer_igen_när_kupén_svalnat_och_stänger_när_varm():
    st = {}
    assert step(st, at(7, 10), "off", 17.0)[0] == "on"         # varm 06:45, kall 07:10
    assert step(st, at(7, 12), "off", 20.5) == (None, None)    # bara 0,5 under: ingen cykling
    assert step(st, at(7, 15), "heat_cool", 21.0)[0] == "off"
    assert step(st, at(7, 16), "heat_cool", 19.0) == (None, None)


def test_avslutas_när_kabeln_dras_ur_och_förblir_avslutad():
    st = {}
    assert step(st, at(7, 0), "off", 16.0, conn=True)[0] == "on"
    act, why = step(st, at(7, 10), "off", 16.0, conn=False)    # föraren drog ur kabeln
    assert act is None and "hämtad" in why
    assert step(st, at(7, 12), "off", 12.0, conn=True) == (None, None)   # inkopplad igen: rör inte


def test_avslutas_när_bilen_flyttas():
    st = {}
    act, why = step(st, at(7, 10), "off", 16.0, away=True)
    assert act is None and "hämtad" in why


def test_utan_kabel_hela_tiden_håller_den_på():
    st = {}
    assert step(st, at(7, 10), "off", 16.0, conn=False)[0] == "on"       # aldrig inkopplad: ingen utsignal att vänta på


def test_nästa_dag_börjar_om():
    st = {}
    step(st, at(7, 10), away=True)
    assert st["ended"]
    assert step(st, at(7, 0, day=25), "off", 15.0)[0] == "on"


def test_okänd_temperatur_gör_inget():
    assert step({}, at(7, 10), "off", None) == (None, None)


def test_hålltiden_sparas_och_läses(db):
    import settings
    assert settings.save_climate_schedule_db("bil_x", True, "06:45", 21.0, 45)
    row = settings.get_climate_schedule(["bil_x"])["bil_x"]
    assert row["hold_min"] == 45 and row["target_time"] == "06:45"
    assert settings.save_climate_schedule_db("bil_x", True, "06:45", 21.0)           # äldre anrop utan hålltid
    assert settings.get_climate_schedule(["bil_x"])["bil_x"]["hold_min"] == 0
