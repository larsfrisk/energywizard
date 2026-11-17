"""plan_clock.py - data till den dragbara planklockan (webben och mobilappen, static/planclock.js).

En rad per kvart från nu och 24 timmar framåt: pris (totalt och spot), vad husbatteriet planerar (laddar/laddar ur/
sparas/vilar, kW och nivån efter kvarten), hur mycket varje bil planeras ladda, värmepumpens grundläge och
solprognosen. Bygger ingen egen plan - läser motorns sparade planer (battery_plan_slots, ev_plan_slots) och samma
värmelägen och solprognos som tidslinjen (timeline.py).
"""
from datetime import datetime, timedelta, timezone
import calendar
import math
import zoneinfo

import plan_brief

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
SLOT = timedelta(minutes=15)


def _q(ts):
    """Kvarten som ts ligger i (svensk tid)."""
    ts = ts.astimezone(SWE) if ts.tzinfo else ts.replace(tzinfo=SWE)
    return ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)


def _daylight(ts, latitude, longitude):
    """Approximate visible sun using NOAA's solar-position equations (UTC).

    https://gml.noaa.gov/grad/solcalc/solareqns.PDF
    Includes the standard 0.833 degree sunrise/refraction allowance.
    """
    ts = ts.astimezone(timezone.utc)
    hour = ts.hour + ts.minute / 60 + ts.second / 3600
    year_days = 366 if calendar.isleap(ts.year) else 365
    g = 2 * math.pi / year_days * (ts.timetuple().tm_yday - 1 + (hour - 12) / 24)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    angle = math.radians((hour * 60 + eq + 4 * longitude) / 4 - 180)
    lat = math.radians(latitude)
    elevation_sine = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(angle)
    return elevation_sine > math.sin(math.radians(-0.833))


def build(now, prices, ev_rows=(), bat_rows=(), heat_modes=None, solar_w=None, full_cost=None, location=None):
    """Ren funktion (testas utan databas).
    prices: [(t, spot)] per kvart eller timme. ev_rows: [(bil, t_slot, kw)]. bat_rows: [(t_slot, action, soc, spot, kw)].
    heat_modes: {timme: 'CHEAP'|'COMFORT'|'EXPENSIVE'}. solar_w: {timme: W}. full_cost(spot, t) -> totalpris.
    location: (latitude, longitude), masks solar display in fully dark quarters only."""
    q0 = _q(now)
    end = q0 + timedelta(hours=24)
    spot = {}
    for t, p in prices or []:
        if p is None:
            continue
        t = t.astimezone(SWE) if t.tzinfo else t.replace(tzinfo=SWE)
        step = 4 if t.minute == 0 and not any(_q(x[0]) == t + SLOT for x in prices or []) else 1   # timpris -> fyra kvartar
        for k in range(step):
            spot.setdefault(_q(t + k * SLOT), float(p))
    ev = {}
    for car, t, kw in ev_rows or []:
        if kw is None:
            continue
        ev.setdefault(_q(t), {})[str(car)] = round(float(kw), 2)
    bat = {}
    for r in bat_rows or []:
        t, action, soc = r[0], r[1], r[2]
        kw = r[4] if len(r) > 4 else None
        grid = r[5] if len(r) > 5 else None
        if action == "discharge" and grid is not None and float(grid) < -plan_brief.EXPORT_KW:
            action = "export"                                  # laddar ur och säljer - egen färg
        bat[_q(t)] = {"action": action, "soc": None if soc is None else round(float(soc)),
                      "balance": bool(r[6]) if len(r) > 6 else False,
                      "kw": None if kw is None else round(float(kw), 2)}
    heat_modes, solar_w = heat_modes or {}, solar_w or {}
    slots = []
    t = q0
    while t < end:
        s = spot.get(t)
        if s is None and t > q0 + timedelta(hours=1) and not any(k > t for k in spot):
            break                                            # inga priser längre fram - klockan slutar där planen slutar
        hour = t.replace(minute=0)
        b = bat.get(t) or {}
        sun = solar_w.get(hour)
        if sun is not None and location is not None:
            # Hourly/learned forecasts can contain stale positive readings at night.
            # Retain quarters touching sunrise/sunset; never alter the stored forecast or plans.
            if not any(_daylight(t + offset, *location) for offset in (timedelta(), SLOT / 2, SLOT)):
                sun = 0
        slots.append({
            "t": t.isoformat(),
            "spot": None if s is None else round(s, 4),
            "price": None if s is None else round(full_cost(s, t) if full_cost else s, 4),
            "bat": b.get("action"), "bat_kw": b.get("kw"), "soc": b.get("soc"),
            "bat_balance": b.get("balance", False),
            "ev": ev.get(t) or {},
            "heat": heat_modes.get(hour),
            "sun_w": sun,
        })
        t += SLOT
    return {"ok": True, "now": now.astimezone(SWE).isoformat(), "slots": slots}


def load(conn, now=None, cars=None):
    """Läser databasen. cars: [{'id','name'}] ur installationen (namn och ordning till klockans förklaring)."""
    from sqlalchemy import text
    import nordpool
    import plan_brief
    now = (now or datetime.now(SWE)).astimezone(SWE)
    q0 = _q(now)
    prices = conn.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b "
                               "ORDER BY time_start"), {"a": q0 - timedelta(hours=1), "b": q0 + timedelta(hours=25)}).fetchall()
    try:
        ev_rows = conn.execute(text("SELECT car_id, t_slot, kw FROM ev_plan_slots WHERE t_slot >= :a"), {"a": q0}).fetchall()
    except Exception:
        conn.rollback()
        ev_rows = []
    bat_rows = plan_brief.load_battery_rows(conn)
    heat_modes = {}
    try:
        cheap = conn.execute(text("SELECT cheap_hours_count FROM system_settings WHERE id = 1")).scalar() or 8
        mode_now = conn.execute(text("SELECT active_mode FROM sensor_log WHERE active_mode IS NOT NULL "
                                     "ORDER BY timestamp DESC LIMIT 1")).scalar()
        q_today = conn.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a ORDER BY time_start"),
                               {"a": q0.replace(hour=0, minute=0)}).fetchall()
        for it in plan_brief.heat_items([(t, float(p)) for t, p in q_today if p is not None], now,
                                        nordpool.calculate_day_strategy, int(cheap), mode_now):
            s, e = datetime.fromisoformat(it["start"]), datetime.fromisoformat(it["end"])
            s = s.replace(minute=0, second=0, microsecond=0)
            while s < e:
                heat_modes.setdefault(s.astimezone(SWE), it["mode"])
                s += timedelta(hours=1)
    except Exception:
        conn.rollback()
    solar, location = {}, None
    try:
        import weather
        location = weather.refresh_location()
        for k in range(0, 25):
            hh = q0.replace(minute=0) + timedelta(hours=k)
            cloud, _, _, _ = weather.get_weather_at(hh)
            w = weather.get_hourly_solar_w(cloud, hh)
            if w is not None:
                solar[hh] = round(float(w))
    except Exception:
        pass
    out = build(now, [(r[0], r[1]) for r in prices], [tuple(r) for r in ev_rows], [tuple(r) for r in bat_rows],
                heat_modes, solar, nordpool.full_buy_cost, location=location)
    out["cars"] = cars or []
    try:
        out["has_battery"] = bool(bat_rows)
    except Exception:
        out["has_battery"] = False
    return out
