"""ML-valt börvärde (Emil 2026-11-15) och golvvakten på de två kallaste rummen."""
import os
import random
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import heat_ml

SWE = ZoneInfo("Europe/Stockholm")
SANT = [-0.40, 0.006, 0.016, -0.002]          # som Emils hus


def _syntetiskt(n_q=4000, seed=1):
    rnd = random.Random(seed)
    t0 = datetime(2026, 10, 1)
    rows, tin, sp = [], 21.0, 19.0
    for i in range(n_q):
        if i % 16 == 0:
            sp = rnd.choice([15, 17, 19, 20, 21, 23])
        tout = 3 + 3 * rnd.random()
        prev = [r[2] for r in rows[-8:]] or [sp]
        tin += heat_ml.rate(SANT, sp, sum(prev) / len(prev), tin, tout) / 4 + rnd.gauss(0, 0.01)
        tin = min(max(tin, 18), 24)
        rows.append((t0 + timedelta(minutes=15 * i), round(tin, 1), sp, tout, 0))
    return rows


def test_modellen_hittar_sambandet():
    w, n = heat_ml.fit(_syntetiskt())
    assert w and n >= heat_ml.MIN_SAMPLES
    assert abs((w[1] + w[2]) - (SANT[1] + SANT[2])) < 0.01         # effekt per grad börvärde


def test_för_lite_data_ger_ingen_modell():
    assert heat_ml.fit(_syntetiskt(200))[0] is None


def test_dyrt_väljer_lägsta_som_håller_golvet():
    # 21,0 °C i de kallaste rummen, 2 h till billigt: lågt börvärde räcker
    sp, why = heat_ml.choose(SANT, "EXPENSIVE", 21.0, 21.4, 2.0, 2.0, 20.0, 22.0, 15.0, 25.0)
    assert sp == 15.0
    # 20,5 °C och 8 h till billigt: måste hålla emot -> högre börvärde
    sp2, _ = heat_ml.choose(SANT, "EXPENSIVE", 20.5, 21.0, 2.0, 8.0, 20.0, 22.0, 15.0, 25.0)
    assert sp2 > 15.0
    end = heat_ml.predict_end(SANT, 20.5, sp2, 21.0, 2.0, 8.0)
    assert end >= 20.2


def test_billigt_väljer_högsta_under_taket():
    sp, _ = heat_ml.choose(SANT, "CHEAP", 20.8, 21.0, 2.0, 3.0, 20.0, 22.0, 15.0, 25.0)
    assert heat_ml.predict_end(SANT, 21.0, sp, 21.0, 2.0, 3.0) <= 21.7
    assert sp == 25.0 or heat_ml.predict_end(SANT, 21.0, sp + 0.5, 21.0, 2.0, 3.0) > 21.7


def test_motorn_golvvakt_på_två_kallaste_och_ml():
    from test_heat_feedback import NOW
    from gpm import GlobalPriorityManager
    base = {"now": NOW, "car_ids": [], "indoor_temp": 21.0, "indoor_min": 19.0, "indoor_max": 22.0,
            "temp_cheap": 22.0, "temp_expensive": 20.0, "current_price": 2.0, "dynamic_limit": 1.0, "hysteresis": 0.1,
            "outdoor_avg_5d": 2.0, "heat_stop_outdoor": 17.0, "heat_feedback": "på", "outdoor_temp": 2.0,
            "heat_feedback_min_sp": 15.0, "heat_feedback_max_sp": 25.0}
    # Medianen 21,0 men de två kallaste 20,3: golvvakten höjer
    a = GlobalPriorityManager().evaluate({**base, "indoor_low2": 20.3})
    assert a["pump_target_temp"] == 21.0 and any("två kallaste" in l for l in a["log"])
    # ML: 6 h till billigt, kallaste 20,6 -> inte 15 (gamla regeln gav 15)
    a = GlobalPriorityManager().evaluate({**base, "indoor_low2": 20.6, "heat_ml_w": SANT, "heat_horizon": (6.0, 0.0)})
    assert 15.0 < a["pump_target_temp"] <= 21.0 and any("ML:" in l for l in a["log"])
