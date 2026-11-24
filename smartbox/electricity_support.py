"""Month-to-date estimate under the Swedish government proposal KN2026/02195."""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import math
from time import monotonic
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text

STOCKHOLM = ZoneInfo("Europe/Stockholm")
THRESHOLD = 1.50
COVERED_SHARE = 0.90
IMPORT_CAP_KWH = 5000
AREAS = ("SE1", "SE2", "SE3", "SE4")


def eligible_area(settings, now):
    month = now.astimezone(STOCKHOLM).date().replace(day=1)
    area = settings["area"]
    if settings["country"] != "SE" or area not in AREAS:
        return None
    if (month == date(2026, 10, 1) and area == "SE4") or month in (date(2026, 11, 1), date(2026, 12, 1)):
        return area
    return None


def month_to_date(now):
    month = now.astimezone(STOCKHOLM).date().replace(day=1)
    end = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return _midnight(month), end


def _midnight(day):
    return datetime.combine(day, time.min, STOCKHOLM).astimezone(timezone.utc)


@lru_cache(maxsize=368)
def _daily_spot(area, day):
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{day:%Y/%m-%d}_{area}.json"
    response = requests.get(url, timeout=3, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError("Spot prices unavailable")
    intervals = sorted(
        (datetime.fromisoformat(row["time_start"]), datetime.fromisoformat(row["time_end"]), float(row["SEK_per_kWh"]))
        for row in response.json()
    )
    cursor = _midnight(day)
    day_end = _midnight(day + timedelta(days=1))
    for start, end, rate in intervals:
        if start != cursor or not start < end <= day_end or not math.isfinite(rate):
            raise ValueError("Incomplete spot price series")
        cursor = end
    if cursor != day_end:
        raise ValueError("Incomplete spot price series")
    return intervals


def spot_average(area, start, end):
    """Elapsed-time average from a complete, explicitly area-specific VAT-free series."""
    if area not in AREAS or end <= start:
        return None
    day = start.astimezone(STOCKHOLM).date()
    total = 0.0
    deadline = monotonic() + 12
    try:
        while _midnight(day) < end:
            if monotonic() >= deadline:
                return None
            for a, b, price in _daily_spot(area, day):
                seconds = (min(b, end) - max(a, start)).total_seconds()
                if seconds > 0:
                    total += price * seconds
            day += timedelta(days=1)
    except (requests.RequestException, KeyError, TypeError, ValueError, OverflowError):
        return None
    avg = total / (end - start).total_seconds()
    return avg if math.isfinite(avg) else None


def grid_import(conn, start, end):
    """Measured import only, using the same minute-based power integration as Ekonomi."""
    kwh, count = conn.execute(text("""
        SELECT sum(watts) / 60000.0, count(*) FROM (
            SELECT avg(GREATEST(net_power, 0)) AS watts
            FROM sensor_log
            WHERE timestamp >= :start AND timestamp < :end
              AND net_power > CAST('-Infinity' AS numeric) AND net_power < CAST('Infinity' AS numeric)
            GROUP BY date_trunc('minute', timestamp)
        ) AS minute_import
    """), {"start": start, "end": end}).one()
    expected = (end - start).total_seconds() / 60
    return (float(kwh) if count else None), (count / expected if expected else 0)


def estimate_kr(avg, imported_kwh):
    if avg is None or imported_kwh is None:
        return None
    return round(max(0, avg - THRESHOLD) * COVERED_SHARE * min(imported_kwh, IMPORT_CAP_KWH), 2)
