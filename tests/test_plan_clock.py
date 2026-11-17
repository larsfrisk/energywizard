"""plan_clock.build: en rad per kvart 24 h framåt med pris, batteri, bilar, värme och sol."""
from datetime import datetime, timedelta
import zoneinfo

import plan_clock

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")


def test_november_night_solar_is_hidden_without_changing_plans():
    now = datetime(2026, 11, 17, 8, tzinfo=SWE)
    prices = [(now + timedelta(minutes=15 * k), 1.0) for k in range(96)]
    solar = {now.replace(hour=h): 500 for h in range(8, 24)}
    bat = [(now.replace(hour=21), "discharge", 45, 1.0, -2.0)]
    d = plan_clock.build(now, prices, bat_rows=bat, solar_w=solar, location=(57.6797, 14.1293))
    night = [s for s in d["slots"] if s["t"].startswith("2026-11-17T21:")]
    assert len(night) == 4 and all(s["sun_w"] == 0 for s in night)
    assert night[0]["bat"] == "discharge" and night[0]["bat_kw"] == -2.0
    noon = next(s for s in d["slots"] if s["t"].startswith("2026-11-17T12:00"))
    assert noon["sun_w"] == 500 and noon["price"] == 1.0
    assert solar[now.replace(hour=21)] == 500  # original forecast untouched
    assert d["slots"][-1]["sun_w"] is None  # missing data stays unknown


def test_daylight_uses_date_location_and_absolute_time():
    summer = datetime(2026, 6, 21, 21, tzinfo=SWE)
    assert plan_clock._daylight(summer, 57.6797, 14.1293)
    winter = datetime(2026, 11, 17, 21, tzinfo=SWE)
    assert not plan_clock._daylight(winter, 57.6797, 14.1293)
    assert plan_clock._daylight(winter, 40.7, -74.0)  # afternoon in New York
    assert plan_clock._daylight(summer, 69.65, 18.96)  # midnight sun season
    assert not plan_clock._daylight(datetime(2026, 12, 21, 12, tzinfo=SWE), 69.65, 18.96)
    assert plan_clock._daylight(winter, 40.7, -74.0) == plan_clock._daylight(
        winter.astimezone(zoneinfo.ZoneInfo("UTC")), 40.7, -74.0)


def test_summer_evening_solar_is_preserved():
    now = datetime(2026, 6, 21, 21, tzinfo=SWE)
    d = plan_clock.build(now, [(now, 1.0)], solar_w={now: 500}, location=(57.6797, 14.1293))
    assert all(s["sun_w"] == 500 for s in d["slots"][:4])


def test_kvartar_med_plan():
    now = datetime(2026, 11, 5, 17, 37, tzinfo=SWE)
    q0 = datetime(2026, 11, 5, 17, 30, tzinfo=SWE)
    prices = [(q0 + timedelta(minutes=15 * k), 1.0 + k / 100) for k in range(96)]
    d = plan_clock.build(now, prices, ev_rows=[("leaf", q0 + timedelta(hours=3), 4.6)],
                         bat_rows=[(q0 + timedelta(hours=1), "discharge", 40, 1.2, -1.7)],
                         heat_modes={q0.replace(minute=0): "EXPENSIVE"}, solar_w={(q0 + timedelta(hours=18)).replace(minute=0): 3000},
                         full_cost=lambda s, t: s + 0.5)
    sl = d["slots"]
    assert len(sl) == 96 and sl[0]["t"].startswith("2026-11-05T17:30")
    assert sl[0]["price"] == 1.5 and sl[0]["heat"] == "EXPENSIVE"
    assert sl[4]["bat"] == "discharge" and sl[4]["bat_kw"] == -1.7 and sl[4]["soc"] == 40
    assert sl[12]["ev"] == {"leaf": 4.6}
    assert sl[72]["sun_w"] == 3000


def test_timpriser_blir_fyra_kvartar_och_klockan_slutar_med_priserna():
    now = datetime(2026, 11, 5, 17, 5, tzinfo=SWE)
    h0 = datetime(2026, 11, 5, 17, 0, tzinfo=SWE)
    d = plan_clock.build(now, [(h0 + timedelta(hours=k), 2.0) for k in range(7)])
    assert len(d["slots"]) == 28 and all(s["spot"] == 2.0 for s in d["slots"])


def test_urladdning_som_saljer_far_egen_farg():
    """Anders på Discord: laddar ur för eget bruk (orange) skiljs från laddar ur och säljer (egen färg)."""
    import plan_brief
    now = datetime(2026, 11, 5, 17, 2, tzinfo=SWE)
    q0 = datetime(2026, 11, 5, 17, 0, tzinfo=SWE)
    rows = [(q0, "discharge", 60, 2.0, -2.0, -0.05), (q0 + timedelta(minutes=15), "discharge", 55, 2.1, -3.0, -1.4),
            (q0 + timedelta(minutes=30), "discharge", 50, 2.2, -3.0, -1.2)]
    items = plan_brief.battery_items(rows, now)
    assert [i["action"] for i in items] == ["discharge", "export"]
    assert items[1]["title"] == "🔋 Batteriet laddar ur och säljer" and items[1]["price_peak"] == 2.2
    d = plan_clock.build(now, [(q0 + timedelta(minutes=15 * k), 1.0) for k in range(8)], bat_rows=rows)
    assert [s["bat"] for s in d["slots"][:3]] == ["discharge", "export", "export"]
