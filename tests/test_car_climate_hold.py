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


def test_urdragen_kabel_avslutar_inte_hålltiden():
    st = {}
    assert step(st, at(7, 0), "off", 16.0, conn=True)[0] == "on"
    assert step(st, at(7, 10), "off", 16.0, conn=False)[0] == "on"     # kabeln ur: värmen hålls ändå (föraren kan sitta kvar)
    assert not st.get("ended")


def test_avslutas_när_bilen_flyttas_och_förblir_avslutad():
    st = {}
    act, why = step(st, at(7, 10), "off", 16.0, away=True)
    assert act is None and "hämtad" in why
    assert step(st, at(7, 12), "off", 12.0, away=False) == (None, None)    # tillbaka hem samma morgon: rör inte


def test_utan_kabel_hela_tiden_håller_den_på():
    st = {}
    assert step(st, at(7, 10), "off", 16.0, conn=False)[0] == "on"


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


# ---- veckoschema med två tider per dag (#598) -------------------------------------------------------------------------------
def _week():
    w = cc.default_week()
    w[1][0] = {"enabled": True, "time": "06:45"}     # tisdag morgon
    w[1][1] = {"enabled": True, "time": "16:30"}     # tisdag hemresa
    w[2][0] = {"enabled": True, "time": "07:30"}     # onsdag morgon, annan tid
    return w


def test_nästa_tid_väljer_rätt_tid_och_dag():
    w = _week()
    tue = lambda h, m: datetime(2026, 11, 24, h, m, tzinfo=TZ)      # 2026-11-24 är en tisdag
    assert cc.next_target(w, tue(6, 0)) == tue(6, 45)
    assert cc.next_target(w, tue(7, 0)) == tue(16, 30)              # efter morgonen: hemresan
    assert cc.next_target(w, tue(17, 0)) == datetime(2026, 11, 25, 7, 30, tzinfo=TZ)   # nästa dag har annan tid
    assert cc.next_target(cc.default_week(), tue(6, 0)) is None


def test_hålltid_per_tid_i_veckoschemat():
    w = _week()
    tue = lambda h, m: datetime(2026, 11, 24, h, m, tzinfo=TZ)
    assert cc.hold_target(w, tue(7, 10), 45) == tue(6, 45)
    assert cc.hold_target(w, tue(16, 50), 45) == tue(16, 30)        # hemresans hålltid
    assert cc.hold_target(w, tue(12, 0), 45) is None
    assert cc.hold_target(w, tue(7, 10), 0) is None
    # hold_step tar datumtiden direkt
    st = {}
    assert cc.hold_step(st, tue(7, 10), tue(6, 45), 45, 21.0, "off", 15.0, False, False)[0] == "on"
    assert cc.hold_step({}, tue(8, 10), tue(6, 45), 45, 21.0, "off", 15.0, False, False) == (None, None)


def test_normalize_week():
    w = cc.normalize_week(_week())
    assert w[1][1] == {"enabled": True, "time": "16:30"}
    assert cc.normalize_week(None) == cc.default_week()
    for bad in ([], [[]] * 6, [[{}, {}, {}]] * 7, [[{"enabled": True, "time": "25:00"}, {}]] * 7):
        with pytest.raises(ValueError):
            cc.normalize_week(bad)


def test_veckoschemat_sparas_och_läses(db):
    import settings
    w = _week()
    assert settings.save_climate_schedule_db("bil_w", True, "06:45", 21.0, 30, w)
    got = settings.get_climate_schedule(["bil_w"])["bil_w"]
    assert got["week"][1] == w[1] and got["week"][2][0]["time"] == "07:30" and got["enabled"] is True and got["hold_min"] == 30
    # äldre rad utan veckoschema: samma tid alla dagar som första tid
    db.execute("DELETE FROM climate_schedule_week WHERE car_id = 'bil_w'")
    old = settings.get_climate_schedule(["bil_w"])["bil_w"]
    assert old["week"][4][0] == {"enabled": True, "time": "06:45"} and old["week"][4][1]["enabled"] is False
