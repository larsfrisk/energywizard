from datetime import datetime

import spa_bath_learn as L

NOW = datetime(2026, 11, 22, 12, 0)


def test_samma_bad_inom_fyra_timmar_raknas_en_gang():
    log, new1 = L.record([], datetime(2026, 11, 15, 19, 30))
    log, new2 = L.record(log, datetime(2026, 11, 15, 21, 0))
    log, new3 = L.record(log, datetime(2026, 11, 16, 7, 30))
    assert (new1, new2, new3) == (True, False, True) and len(log) == 2


def test_for_litet_underlag_sager_det_rakt_ut():
    s = L.suggest(["2026-11-15T19:30"], NOW)
    assert s["windows"] is None and "minst 3" in s["text"] and s["n"] == 1
    assert L.suggest([], NOW)["windows"] is None


def test_forslag_ger_fonster_runt_badtimmarna_per_veckodag():
    log = ["2026-11-01T19:00", "2026-11-08T19:30", "2026-11-15T19:30", "2026-11-14T10:00"]   # tre sön, en lör
    s = L.suggest(log, NOW)
    w = s["windows"]
    assert len(w) == 7 and s["mode"] == "bath"
    assert w[6] == {"on": True, "from": "17:00", "to": "22:30"}          # sön 19:00-19:30 -> 17:00-22:30
    assert w[5]["on"] and w[5]["from"] == "08:00" and w[5]["to"] == "13:00"
    assert not any(w[i]["on"] for i in range(5))
    assert "söndagar" in s["text"] and "3 bad" in s["text"]


def test_gamla_bad_utanfor_tolv_veckor_ignoreras():
    log = ["2026-01-04T19:00", "2026-01-11T19:00", "2026-01-18T19:00", "2026-11-15T19:30"]
    assert L.suggest(log, NOW)["windows"] is None


def test_tider_klipps_inom_dygnet():
    log = ["2026-11-02T00:30", "2026-11-09T00:20", "2026-11-16T23:50"]
    w = L.suggest(log, NOW)["windows"]
    assert w[0]["from"] == "00:00" and w[0]["on"]
    assert w[0]["to"] > w[0]["from"]
    assert w[6]["to"] <= "23:59"
