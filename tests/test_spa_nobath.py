"""Spabadet: tider då man INTE badar (Emil 2026-11-15). Under dem får badet svalna och värms på de billigaste timmarna
så att det är varmt när tiden tar slut; all annan tid är badtid. Tiderna får gå över midnatt."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import spa_bath

Z = ZoneInfo("Europe/Stockholm")
VARDAG = {"on": True, "from": "22:00", "to": "16:00"}       # natt + arbetsdag
HELG = {"on": True, "from": "23:00", "to": "10:00"}
RAW = [VARDAG] * 5 + [HELG] * 2


def t(s):
    return datetime.fromisoformat(s).replace(tzinfo=Z)


def test_under_inga_bad_planeras_värmen_till_slutet():
    assert spa_bath.status(t("2026-11-17 09:00"), RAW, "nobath") == (False, t("2026-11-17 16:00"), None)


def test_mellan_inga_bad_tiderna_är_det_badtid():
    assert spa_bath.status(t("2026-11-17 18:00"), RAW, "nobath") == (True, None, t("2026-11-17 22:00"))


def test_över_midnatt():
    assert spa_bath.status(t("2026-11-17 23:30"), RAW, "nobath") == (False, t("2026-11-18 16:00"), None)


def test_helgen():
    # fredag 22:00 -> lördag 16:00 (fredagens post), lördag 23:00 -> söndag 10:00
    assert spa_bath.status(t("2026-11-21 12:00"), RAW, "nobath") == (False, t("2026-11-21 16:00"), None)
    assert spa_bath.status(t("2026-11-22 08:00"), RAW, "nobath") == (False, t("2026-11-22 10:00"), None)


def test_inga_dagar_ingen_styrning():
    assert spa_bath.status(t("2026-11-17 09:00"), None, "nobath") == (False, None, None)


def test_clean_tillåter_över_midnatt_bara_i_inga_bad_läget():
    rows = [dict(VARDAG)] + [{"on": False}] * 6
    assert spa_bath.clean(rows, "nobath")[0]["on"] is True
    assert spa_bath.clean(rows, "bath") is None                   # 22-16 är ogiltigt som badtid


def test_badtidsläget_som_förut():
    raw = [{"on": True, "from": "17:00", "to": "21:00"}] * 7
    assert spa_bath.status(t("2026-11-17 18:00"), raw) == (True, t("2026-11-17 17:00"), t("2026-11-17 21:00"))


def test_motorn_läser_läget():
    src = open(os.path.join(ROOT, "smartbox", "main.py"), encoding="utf-8").read()
    assert 'spa_bath.status(now, _ew_settings.get("spa_bath_windows"), _bath_mode)' in src
