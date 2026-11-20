"""Flödet märker en manuell laddning ("Ladda nu") från servern, så att både appen och webbens Översikt visar den."""
from pathlib import Path
from unittest.mock import MagicMock

import live_flow

ROOT = Path(__file__).resolve().parents[1]
ROW = {"ev_power_kw": 4.4, "ev_carport_power_kw": 0.0, "nissan_soc": 64, "tesla_soc": 52}
CARS = [("nissan", "Nissan", "ev_power_kw"), ("tesla", "Tesla", "ev_carport_power_kw")]


def _ev(d):
    return {n["key"]: n for n in d["nodes"] if n["key"].startswith("ev_")}


def test_only_the_charging_manual_car_is_marked():
    ev = _ev(live_flow.nodes(ROW, [], cars=CARS, manual_cars={"nissan", "tesla"}))
    assert ev["ev_nissan"]["manual"] is True
    assert "manual" not in ev["ev_tesla"]                      # Tesla laddar inte: inget "ladda nu" från servern


def test_no_manual_cars_means_no_marking():
    for kw in ({}, {"manual_cars": None}, {"manual_cars": set()}):
        assert all("manual" not in n for n in live_flow.nodes(ROW, [], cars=CARS, **kw)["nodes"])


def test_manual_charge_cars_reads_force_amps_only():
    conn = MagicMock()
    conn.execute.return_value = [("nissan_force_amps", "20"), ("tesla_force_amps", "0"), ("volvo_ex40_force_amps", "16.0"),
                                 ("kia_force_amps", "x"), ("saknas_force_amps", None)]
    assert live_flow.manual_charge_cars(conn) == {"nissan", "volvo_ex40"}


def test_manual_charge_cars_survives_a_database_error():
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("db nere")
    assert live_flow.manual_charge_cars(conn) == set()


def test_both_surfaces_pass_the_manual_cars_to_the_flow():
    for f in ("ewapp/app.py", "webdashboard/app.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "live_flow.manual_charge_cars(c)" in src and "manual_cars=manual" in src, f
