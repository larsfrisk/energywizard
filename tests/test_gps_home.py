"""GPS-hemkomst (2026-11-15): ingen "närmar sig" på första avläsningen efter omstart, flaggan släpper när bilen slutar
närma sig, och en bil som bara är på väg hem räknas inte som inkopplad av kontaktorskyddet."""
import os
import sys
import zoneinfo
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import gps_home

T0 = datetime(2026, 11, 15, 13, 21)


def test_första_avläsningen_efter_omstart_är_inte_närmande():
    app, closer, ref = gps_home.approaching(False, 1.7, None, None, False, T0)
    assert app is False and ref == 1.7


def test_stillastående_bil_släpper_efter_tidsgränsen():
    app, closer, ref = gps_home.approaching(False, 1.5, 1.8, None, False, T0)       # 0,3 km närmare
    assert app is True
    app, closer, ref = gps_home.approaching(True, 1.5, ref, closer, False, T0 + timedelta(minutes=5))
    assert app is True
    app, closer, ref = gps_home.approaching(True, 1.5, ref, closer, False, T0 + timedelta(minutes=11))
    assert app is False


def test_långsamt_närmande_i_små_steg_räknas():
    ref, app, closer = 5.0, False, None
    t = T0
    for d in (4.95, 4.9, 4.85, 4.78):
        t += timedelta(seconds=10)
        app, closer, ref = gps_home.approaching(app, d, ref, closer, False, t)
    assert app is True


def test_inkopplad_eller_hemma_är_inte_närmande():
    assert gps_home.approaching(True, 1.0, 2.0, T0, True, T0)[0] is False
    assert gps_home.approaching(True, 0.3, 2.0, T0, False, T0)[0] is False


def test_kontaktorskyddet_gäller_bara_inkopplade_bilar():
    from gpm import GlobalPriorityManager
    from test_marginal_spapaus import _state
    swe = zoneinfo.ZoneInfo("Europe/Stockholm")
    g = GlobalPriorityManager()
    nu = datetime(2026, 11, 15, 13, 22, tzinfo=swe)
    g.ev_charging_since["nissan"] = nu - timedelta(minutes=8)
    a = g.evaluate(_state(nu, nissan_connected=True, nissan_plugged=False, nissan_charge_completed=False, nissan_soc=94.0))
    assert not any("BATTERISKYDD" in l and "Nissan" in l for l in a["log"])
    assert g.ev_charging_since.get("nissan") is None
