"""Prio 5b, rumsåterkoppling: börvärdet väljs efter rumsgivarna. Dyrt + varmt hus -> golv - 1, nära golvet -> golv + 1,
billigt -> billig temp + 1 tills huset är 0,5 °C under maxgränsen. Skugga loggar bara. Av = som förut."""
import os
import sys
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from gpm import GlobalPriorityManager

NOW = datetime(2026, 11, 14, 13, 0)


def run(indoor, price, mode="på", **kw):
    st = {"now": NOW, "car_ids": [], "indoor_temp": indoor, "indoor_min": 19.0, "indoor_max": 22.0,
          "temp_cheap": 22.0, "temp_expensive": 20.0, "current_price": price, "dynamic_limit": 1.0, "hysteresis": 0.1,
          "outdoor_avg_5d": 2.0, "heat_stop_outdoor": 17.0, "heat_feedback": mode, **kw}
    a = GlobalPriorityManager().evaluate(st)
    return a, [l for l in a["log"] if "Prio 5b" in l]


def test_dyrt_och_varmt_hus_sänker_till_golv_minus_ett():
    a, log = run(21.6, 2.0)
    assert a["pump_mode"] == "EXPENSIVE" and a["pump_target_temp"] == 19.0
    assert "Dyrt och huset har värme att ge av" in log[0]


def test_dyrt_nära_golvet_höjer():
    a, _ = run(20.3, 2.0)
    assert a["pump_target_temp"] == 21.0


def test_dyrt_mellan_ger_golvet():
    a, _ = run(20.45, 2.0)
    assert a["pump_target_temp"] == 20.0


def test_billigt_lagrar_med_en_grad_extra_tills_under_max():
    a, log = run(21.0, 0.2)
    assert a["pump_mode"] == "CHEAP" and a["pump_target_temp"] == 23.0 and "lagrar värme" in log[0]
    a, _ = run(21.6, 0.2)
    assert a["pump_target_temp"] == 20.0


def test_över_max_tar_hårda_stoppen_över():
    a, log = run(22.1, 0.2)
    assert not log and a["pump_target_temp"] < 20.0


def test_skugga_ändrar_inget():
    a_av, _ = run(21.6, 2.0, mode="av")
    a_sk, log = run(21.6, 2.0, mode="skugga")
    assert a_sk["pump_target_temp"] == a_av["pump_target_temp"] == 20.0
    assert "skulle sätta 19.0 °C" in log[0]


def test_av_som_förut_och_kallt_hus_går_före():
    _, log = run(21.6, 2.0, mode="av")
    assert not log
    a, log = run(18.5, 2.0)
    assert not log and a["pump_target_temp"] == 22.0      # Prio 5: kallt inne, tvingar värme


def test_intervall_från_inställningen():
    a, _ = run(21.6, 2.0, heat_feedback_min_sp=16.0, heat_feedback_max_sp=24.0)
    assert a["pump_target_temp"] == 16.0
    a, _ = run(21.0, 0.2, heat_feedback_min_sp=16.0, heat_feedback_max_sp=24.0)
    assert a["pump_target_temp"] == 24.0


def test_intervallet_begränsas_till_15_25():
    a, _ = run(21.6, 2.0, heat_feedback_min_sp=10.0)
    assert a["pump_target_temp"] == 15.0
    a, _ = run(21.0, 0.2, heat_feedback_max_sp=30.0)
    assert a["pump_target_temp"] == 25.0


def test_golvvakten_gäller_även_med_intervall():
    a, _ = run(20.3, 2.0, heat_feedback_min_sp=15.0, heat_feedback_max_sp=25.0)
    assert a["pump_target_temp"] == 21.0


def _locked(mode):
    g = GlobalPriorityManager()
    g.current_pump_mode = mode
    from datetime import timedelta
    from datetime import timezone
    g.pump_mode_lock_until = NOW.replace(tzinfo=timezone.utc) + timedelta(minutes=30)
    return g


def test_kompressorlåset_skriver_inte_över_återkopplingen():
    # 2026-11-15: Prio 5b satte 19 °C men Prio 8 (låst EXPENSIVE efter lägesbyte) skrev tillbaka 20 °C i 45 min
    g = _locked("EXPENSIVE")
    st = {"now": NOW, "car_ids": [], "indoor_temp": 21.9, "indoor_min": 19.0, "indoor_max": 22.0,
          "temp_cheap": 22.0, "temp_expensive": 20.0, "current_price": 2.0, "dynamic_limit": 1.0, "hysteresis": 0.1,
          "outdoor_avg_5d": 2.0, "heat_stop_outdoor": 17.0, "heat_feedback": "på"}
    a = g.evaluate(st)
    assert any("Prio 8" in l and "Låst" in l for l in a["log"])
    assert a["pump_mode"] == "EXPENSIVE" and a["pump_target_temp"] == 19.0


def test_låst_i_annat_läge_ger_lägets_vanliga_temp():
    # Återkopplingen räknade för billigt, men låset håller kvar dyrt läge -> dyra tempen, inte billig-värdet
    g = _locked("EXPENSIVE")
    st = {"now": NOW, "car_ids": [], "indoor_temp": 20.8, "indoor_min": 19.0, "indoor_max": 22.0,
          "temp_cheap": 22.0, "temp_expensive": 20.0, "current_price": 0.2, "dynamic_limit": 1.0, "hysteresis": 0.1,
          "outdoor_avg_5d": 2.0, "heat_stop_outdoor": 17.0, "heat_feedback": "på"}
    a = g.evaluate(st)
    assert a["pump_mode"] == "EXPENSIVE" and a["pump_target_temp"] == 20.0


def test_låsets_klockslag_visas_i_lokal_tid(monkeypatch):
    import time
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    try:
        g = _locked("EXPENSIVE")      # låst till 13:30 UTC = 14:30 svensk vintertid
        a = g.evaluate({"now": NOW, "car_ids": [], "indoor_temp": 21.0, "indoor_min": 19.0, "indoor_max": 22.0,
                        "temp_cheap": 22.0, "temp_expensive": 20.0, "current_price": 2.0, "dynamic_limit": 1.0,
                        "hysteresis": 0.1, "outdoor_avg_5d": 2.0, "heat_stop_outdoor": 17.0})
        assert any("Prio 8" in l and "14:30" in l for l in a["log"])
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
