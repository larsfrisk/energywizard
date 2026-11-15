"""2026-11-15 (söndag): laddplanen valde nattkvartar för ~1,00 kr före 13:30 för 0,90 kr, för att alla kvartar 07-20 fick
+1,5 kr i poängen - även helger och med effektvakten avstängd. Straffet gäller nu bara effekttariffens höglasttid när
effektvakten är på."""
import zoneinfo
from datetime import datetime, timedelta

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")
SPEC = {"tesla": {"max_a": 16, "phases": "auto", "battery_kwh": 75}}


def _plan(db, start_utc, cfg):
    import decisions
    from test_simulering import fyll_databas
    with db.cursor() as cur:
        cur.execute("DELETE FROM elpriser")
        t = start_utc
        while t < start_utc + timedelta(hours=30):
            h = t.astimezone(SWE).hour
            cur.execute("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (t, 0.90 if h == 13 else 1.00))
            t += timedelta(minutes=15)
    fyll_databas(db, start_utc - timedelta(hours=1), 30)
    nu = start_utc.astimezone(SWE).replace(tzinfo=None)
    dag = {"enabled": True, "target_time": "07:00", "target_soc": 50}
    schema = {"tesla": {d: dict(dag) for d in range(7)}}
    plan = decisions.calculate_ev_charge_plan(nu, schema, {"tesla_soc": 45.0, "tesla_plugged_in": True,
                                                          "tesla_phases": "Three phases", "car_ids": ["tesla"],
                                                          "car_specs": SPEC}, cfg)
    return plan[plan["tesla_kw"] > 0]["t_slot"].dt.hour.tolist()


def test_söndag_laddar_den_billiga_timmen_mitt_på_dagen(smartbox, db):
    timmar = _plan(db, datetime(2026, 11, 15, 12, 0, tzinfo=UTC), {"peak_shaving_enabled": True})   # 13:00 svensk tid
    assert timmar and set(timmar) == {13}, timmar


def test_vardag_med_effektvakten_av_laddar_den_billiga_timmen(smartbox, db):
    timmar = _plan(db, datetime(2026, 11, 16, 12, 0, tzinfo=UTC), {"peak_shaving_enabled": False})
    assert timmar and set(timmar) == {13}, timmar


def test_vardag_med_effektvakten_på_undviker_höglasttid(smartbox, db):
    timmar = _plan(db, datetime(2026, 11, 16, 12, 0, tzinfo=UTC), {"peak_shaving_enabled": True})
    assert timmar and all(h < 7 or h >= 20 for h in timmar), timmar
