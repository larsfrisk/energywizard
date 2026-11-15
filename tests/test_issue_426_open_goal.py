"""#426: laddmål utan klar-tid. Planen räknar över alla kända priser (även morgondagens) och väntar till de billigaste;
morgongolvet går att sänka eller stänga av per bil, annars tvingar ett golv på 50 % fram laddning före 06."""
import zoneinfo
from datetime import datetime, timedelta

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")
SPEC = {"tesla": {"max_a": 16, "phases": "auto", "battery_kwh": 75}}
START = datetime(2026, 11, 16, 21, 0, tzinfo=UTC)          # 22:00 svensk tid
CHEAP = datetime(2026, 11, 17, 13, 0)                      # morgondagens billigaste timme (svensk tid)


def _plan(db, extra):
    import decisions
    from test_simulering import fyll_databas
    with db.cursor() as cur:
        cur.execute("DELETE FROM elpriser")
        t = START
        while t < START + timedelta(hours=26):
            lt = t.astimezone(SWE).replace(tzinfo=None)
            cur.execute("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (t, 0.3 if lt.replace(minute=0) == CHEAP else 1.0))
            t += timedelta(minutes=15)
    fyll_databas(db, START - timedelta(hours=1), 26)
    nu = START.astimezone(SWE).replace(tzinfo=None)
    schema = {"tesla": {d: {"enabled": False, "target_time": "07:00", "target_soc": 80} for d in range(7)}}
    cd = {"tesla_soc": 40.0, "tesla_plugged_in": True, "tesla_phases": "Three phases", "car_ids": ["tesla"], "car_specs": SPEC, **extra}
    plan = decisions.calculate_ev_charge_plan(nu, schema, cd, {"peak_shaving_enabled": False})
    return plan[plan["tesla_kw"] > 0]["t_slot"].tolist() if len(plan) else []


def test_mål_utan_klartid_väntar_på_morgondagens_billiga_timme(smartbox, db):
    slots = _plan(db, {"tesla_open_soc": 50, "tesla_open_until": datetime(2026, 11, 17, 23, 0), "tesla_floor_soc": 0})
    assert slots and all(s.replace(minute=0) == CHEAP for s in slots), slots


def test_golvet_på_50_laddar_fortfarande_före_06(smartbox, db):
    slots = _plan(db, {"tesla_open_soc": 50, "tesla_open_until": datetime(2026, 11, 17, 23, 0)})
    assert slots and all(s < datetime(2026, 11, 17, 6, 0) for s in slots), slots


def test_golvet_av_och_inget_mål_ger_ingen_plan(smartbox, db):
    assert _plan(db, {"tesla_floor_soc": 0}) == []


def test_utan_inställningar_som_förut(smartbox, db):
    slots = _plan(db, {})
    assert slots and all(s < datetime(2026, 11, 17, 6, 0) for s in slots)


def test_open_until_stannar_vid_sista_kända_priset():
    import ev_rules
    nu = datetime(2026, 11, 16, 22, 0)
    assert ev_rules.open_until(nu, 36, datetime(2026, 11, 18, 0, 0)) == datetime(2026, 11, 18, 0, 0)
    assert ev_rules.open_until(nu, 12, datetime(2026, 11, 18, 0, 0)) == nu + timedelta(hours=12)


def test_motorns_morgongolv_följer_bilens_golv():
    from gpm import _needy_morning_cars
    nu = datetime(2026, 11, 16, 3, 0, tzinfo=SWE)
    st = {"a_soc": 30, "a_connected": True, "b_soc": 30, "b_connected": True, "b_floor_soc": 0, "c_soc": 30, "c_connected": True, "c_floor_soc": 20}
    assert _needy_morning_cars(st, ["a", "b", "c"], 50, 6, nu) == ["a"]
