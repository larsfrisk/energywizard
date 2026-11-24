from datetime import date, datetime, timedelta, timezone
import os
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy import create_engine, text

import electricity_support as support


@pytest.mark.parametrize("at,country,area,expected", [
    ("2026-09-30T22:00:00Z", "SE", "SE4", "SE4"),
    ("2026-10-01T10:00:00Z", "SE", "SE3", None),
    ("2026-10-31T23:00:00Z", "SE", "SE3", "SE3"),
    ("2026-12-01T10:00:00Z", "SE", "SE1", "SE1"),
    ("2026-12-01T10:00:00Z", "CZ", "SE1", None),
    ("2026-12-01T10:00:00Z", "SE", "unknown", None),
    ("2026-12-31T23:00:00Z", "SE", "SE4", None),
])
def test_area_and_month_follow_swedish_calendar(at, country, area, expected):
    assert support.eligible_area({"country": country, "area": area}, datetime.fromisoformat(at)) == expected


def test_estimate_caps_measured_grid_import_and_clamps_rate():
    assert support.estimate_kr(1.75, 1000) == 225
    assert support.estimate_kr(1.75, 6200) == 1125
    assert support.estimate_kr(1.50, 1000) == 0
    assert support.estimate_kr(1.20, 1000) == 0
    assert support.estimate_kr(None, 1000) is None
    assert support.estimate_kr(1.75, None) is None


def test_spot_average_uses_area_and_elapsed_time_across_dst(monkeypatch):
    start = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
    day = date(2026, 10, 25)  # Stockholm has 25 hours on this day.
    end = start + timedelta(hours=25)
    rows = [
        {"time_start": (start + timedelta(hours=i)).isoformat(),
         "time_end": (start + timedelta(hours=i + 1)).isoformat(),
         "SEK_per_kWh": 1.0 if i < 12 else 2.0}
        for i in range(25)
    ]
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: rows)

    support._daily_spot.cache_clear()
    monkeypatch.setattr(support.requests, "get", get)
    try:
        assert support.spot_average("SE4", start, end) == pytest.approx(38 / 25)
        assert support.spot_average("SE4", start, start + timedelta(hours=12, minutes=30)) == pytest.approx(13 / 12.5)
        assert urls == ["https://www.elprisetjustnu.se/api/v1/prices/2026/10-25_SE4.json"]
        rows.pop(4)
        assert support.spot_average("SE3", start, end) is None
        assert urls[-1].endswith(f"{day:%Y/%m-%d}_SE3.json")
    finally:
        support._daily_spot.cache_clear()


def test_month_bounds_exclude_current_incomplete_minute():
    start, end = support.month_to_date(datetime.fromisoformat("2026-11-24T12:15:32+01:00"))
    assert start == datetime.fromisoformat("2026-10-31T23:00:00Z")
    assert end == datetime.fromisoformat("2026-11-24T11:15:00Z")


def test_grid_import_counts_each_measured_minute_once(db):
    params = dict(db.info.get_parameters(), password=os.environ["POSTGRES_PASSWORD"])
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(**params))
    start = datetime.fromisoformat("2026-11-01T00:00:00+01:00")
    end = start + timedelta(minutes=5)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE sensor_log (timestamp TIMESTAMPTZ, net_power NUMERIC)"))
            assert support.grid_import(conn, start, end) == (None, 0)
            conn.execute(text("INSERT INTO sensor_log VALUES (:timestamp, :power)"), [
                {"timestamp": start + timedelta(seconds=seconds), "power": power}
                for seconds, power in [
                    (-1, 9000), (0, 3000), (20, 9000), (60, -3000), (120, None),
                    (180, "NaN"), (240, 0), (300, 9000),
                ]
            ])
            assert support.grid_import(conn, start, end) == pytest.approx((0.1, 0.6))
    finally:
        engine.dispose()
