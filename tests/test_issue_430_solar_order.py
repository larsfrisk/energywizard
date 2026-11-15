"""#430: ordningen för solöverskottet (husbatteri, elbil, spabad, varmvatten, hus). En last längre ned startar bara när
ingen högre last vill ha överskottet och kan starta på det; en nyss startad högre last får fem minuter."""
import os
import sys
import zoneinfo
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import solar_order
from test_marginal_spapaus import _state

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
NU = datetime(2026, 11, 16, 12, 0, tzinfo=SWE)


def test_normalize():
    assert solar_order.normalize(None) == solar_order.DEFAULT
    assert solar_order.normalize(["spa", "x", "spa", "ev"]) == ["spa", "ev", "battery", "hotwater", "house"]


def test_blocker():
    info = {"ev": {"wants": True, "active": False, "min_w": 1400}, "spa": {"wants": True, "active": False, "min_w": 1000}}
    assert solar_order.blocker("spa", ["ev", "spa"], info, 2000, NU) == "ev"           # elbilen kan starta: den först
    assert solar_order.blocker("spa", ["ev", "spa"], info, 1200, NU) is None           # för lite för elbilen: badet får
    info["ev"].update(active=True, since=NU - timedelta(minutes=2))
    assert solar_order.blocker("spa", ["ev", "spa"], info, 2000, NU) == "ev"           # nyss startad
    info["ev"]["since"] = NU - timedelta(minutes=10)
    assert solar_order.blocker("spa", ["ev", "spa"], info, 2000, NU) is None           # går redan: överskottet som blir över


def _run(order, **over):
    from gpm import GlobalPriorityManager
    g = GlobalPriorityManager()
    st = _state(NU, nissan_connected=True, nissan_charge_completed=False, nissan_soc=60.0, tesla_connected=False,
                avg_net_w=-3200.0, grid_import_w=0.0, current_price=0.9, all_prices=[0.9] * 96, spa_temp=37.0,
                spa_max_temp=40.0, has_spa=True, solar_order=order, ev_actual_a=0, **over)
    return g, g.evaluate(st)


def test_standardordningen_är_oförändrad():
    # Ingen egen ordning: det inbyggda beteendet, ingen spärr (golden-testet kontrollerar resten)
    g, a = _run(None)
    assert g.ev_solar_charge_active and a.get("solar_order") is None


def test_egen_ordning_elbilen_före_badet():
    g, a = _run(["ev", "spa", "battery", "hotwater", "house"])
    assert g.ev_solar_charge_active and not a.get("spa_solar_boost_active")


def test_badet_före_elbilen():
    g, a = _run(["spa", "ev", "battery", "hotwater", "house"])
    assert a.get("spa_solar_boost_active")
    assert not g.ev_solar_charge_active
    assert any("spabad" in l for l in a["log"] if "SOLAR EV" in l)


def test_batteriets_eftergift(monkeypatch):
    src = open(os.path.join(ROOT, "smartbox", "main.py"), encoding="utf-8").read()
    ns = {}
    start = src.index("def _solar_yield(")
    exec(src[start:src.index("\ndef ", start + 10)], ns)
    info = {"ev": {"wants": True, "active": False, "min_w": 1400}}
    # Standard: batteriet först -> inget att vika för
    assert ns["_solar_yield"]({"solar_order": None, "solar_info": info}, 0.0, 2500.0) is None
    # Elbilen före batteriet: batteriet laddar 2,5 kW av överskottet -> elbilen kan starta -> batteriet vilar
    assert ns["_solar_yield"]({"solar_order": ["ev", "battery"], "solar_info": info}, 0.0, 2500.0) == "elbil"
    # För litet överskott även med batteriets laddning -> batteriet laddar som förut
    assert ns["_solar_yield"]({"solar_order": ["ev", "battery"], "solar_info": info}, 0.0, 800.0) is None


def test_battery_control_regel():
    import battery_control
    d = battery_control.decide({"soc": 60, "price": 0.9, "avg_net_w": -200, "solar_yield_to": "elbil", "meter_fresh": True},
                               {"control": "styr", "reserve_soc": 20, "priority_soc": 50, "max_soc": 100, "max_power_w": 3000}, {"auto", "idle", "charge", "discharge", "hold"})
    assert d["intent"] == "idle" and d["rule"] == "solar_order"
