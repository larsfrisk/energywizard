"""#427 bara sol och #429 maxpris per bil (del av #420). Bara sol: ingen planerad nätladdning, inte heller
morgongolvet. Maxpris: dyrare kvartar tas bort, utom för morgongolvet."""
import zoneinfo
from datetime import datetime, timedelta

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")
SPEC = {"tesla": {"max_a": 16, "phases": "auto", "battery_kwh": 75}}


def _plan(db, soc, extra, prices):
    import decisions
    from test_simulering import fyll_databas
    start = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)                     # 18:00 svensk tid, måndag
    with db.cursor() as cur:
        cur.execute("DELETE FROM elpriser")
        t = start
        while t < start + timedelta(hours=30):
            cur.execute("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (t, prices(t.astimezone(SWE).hour)))
            t += timedelta(minutes=15)
    fyll_databas(db, start - timedelta(hours=1), 30)
    dag = {"enabled": True, "target_time": "07:00", "target_soc": 80}
    cd = {"tesla_soc": soc, "tesla_plugged_in": True, "tesla_phases": "Three phases", "car_ids": ["tesla"], "car_specs": SPEC, **extra}
    plan = decisions.calculate_ev_charge_plan(start.astimezone(SWE).replace(tzinfo=None), {"tesla": {d: dict(dag) for d in range(7)}}, cd,
                                              {"peak_shaving_enabled": False})
    return plan[plan["tesla_kw"] > 0] if len(plan) else plan


def test_bara_sol_planerar_ingen_nätladdning(smartbox, db):
    p = _plan(db, 30.0, {"tesla_grid_allowed": False}, lambda h: 1.0)
    assert len(p) == 0


def test_sol_och_nät_planerar_som_förut(smartbox, db):
    assert len(_plan(db, 30.0, {}, lambda h: 1.0)) > 0


def test_maxpris_tar_bort_dyra_kvartar(smartbox, db):
    # 60 -> 80 % behöver ~17 kWh; den billiga timmen (02) ger bara ~11 kWh. Resten får INTE tas i dyra kvartar.
    p = _plan(db, 60.0, {"tesla_max_price": 1.0}, lambda h: 0.5 if h == 2 else 2.0)
    assert len(p) > 0 and set(p["t_slot"].dt.hour) == {2}


def test_maxpris_gäller_inte_morgongolvet(smartbox, db):
    # 30 % -> golvet 50 % kl 06 laddas även när allt är dyrare än maxpriset
    p = _plan(db, 30.0, {"tesla_max_price": 0.5}, lambda h: 2.0)
    assert len(p) > 0 and all(t.hour < 6 or t.hour >= 18 for t in p["t_slot"])


def test_morgongolvet_i_motorn_respekterar_bara_sol():
    from gpm import _needy_morning_cars
    nu = datetime(2026, 11, 16, 3, 0, tzinfo=SWE)
    st = {"a_soc": 30, "a_connected": True, "b_soc": 30, "b_connected": True, "b_grid_allowed": False}
    assert _needy_morning_cars(st, ["a", "b"], 50, 6, nu) == ["a"]


def test_regler_valideras():
    import ev_rules
    r, err = ev_rules.validate({"grid": False, "max_price": ""})
    assert err is None and r["grid"] is False and r["max_price"] is None
    assert ev_rules.validate({"grid": True, "max_price": "1.5"})[0]["max_price"] == 1.5
    assert ev_rules.validate({"max_price": "abc"})[1]
    assert ev_rules.validate({"max_price": 50})[1]
    assert ev_rules.get("x", {"ev_rules": {}}) == ev_rules.DEFAULT
