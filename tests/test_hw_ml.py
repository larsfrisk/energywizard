"""ML-styrt varmvatten (2026-11-15): startvärdet (30-55 °C på Thermia) efter inlärda vanor och pris. Stoppvärdet
(toppvärmningen) rörs inte; legionella och felskydd går före."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import hw_ml

Z = ZoneInfo("Europe/Stockholm")
KVÄLL = {(d, h): (0.8 if 19 <= h <= 21 else 0.1) for d in range(7) for h in range(24)}   # duschar 19-21


def test_dyrt_utan_tappning_väntar():
    assert hw_ml.choose_start(datetime(2026, 11, 16, 14, 0, tzinfo=Z), "EXPENSIVE", KVÄLL, [], 56)[0] == 30.0


def test_dyrt_men_dusch_snart():
    assert hw_ml.choose_start(datetime(2026, 11, 16, 18, 0, tzinfo=Z), "EXPENSIVE", KVÄLL, [], 72)[0] == 35.0


def test_billigaste_kvarten_före_duschen_fyller():
    prices = [1.0] * 96
    prices[13 * 4:14 * 4] = [0.3] * 4                   # 13-14 billigast före 19
    nu = datetime(2026, 11, 16, 13, 0, tzinfo=Z)
    assert hw_ml.choose_start(nu, "CHEAP", KVÄLL, prices, 52)[0] == 50.0
    nu2 = datetime(2026, 11, 16, 15, 0, tzinfo=Z)          # 15:00 är inte bland de billigaste
    prices2 = [1.0] * 96
    prices2[17 * 4:18 * 4] = [0.3] * 4
    assert hw_ml.choose_start(nu2, "CHEAP", KVÄLL, prices2, 60)[0] == 45.0


def test_motorn_skugga_ändrar_inget_och_legionella_går_före():
    from gpm import GlobalPriorityManager
    from test_heat_feedback import NOW
    base = {"now": NOW, "car_ids": [], "indoor_temp": 21.0, "indoor_min": 19.0, "indoor_max": 22.0, "temp_cheap": 22.0,
            "temp_expensive": 20.0, "current_price": 2.0, "dynamic_limit": 1.0, "hysteresis": 0.1, "outdoor_avg_5d": 2.0,
            "heat_stop_outdoor": 17.0, "water_temp": 50.0, "hw_profile": {}}
    av = GlobalPriorityManager().evaluate(base)["water_target_temp"]
    sk = GlobalPriorityManager().evaluate({**base, "hw_ml": "skugga"})
    assert sk["water_target_temp"] == av and any("I skugga" in l for l in sk["log"])
    på = GlobalPriorityManager().evaluate({**base, "hw_ml": "på"})
    assert på["water_target_temp"] == 35.0                  # start 30
    leg = GlobalPriorityManager().evaluate({**base, "hw_ml": "på", "days_since_legionella": 30, "legionella_max_days": 14})
    assert leg["water_target_temp"] == 60.0
