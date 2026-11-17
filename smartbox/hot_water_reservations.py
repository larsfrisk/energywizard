"""Modelled boost reservations over a separate boost-excluded background forecast."""
from local_sql import local_sql
from datetime import datetime, timedelta
import math


def configuration(house):
    raw = (house.get('battery') or {}).get('hot_water_reservations') or {}
    if raw.get('enabled') is not True:
        return None
    value = raw.get('background_kw')
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
        raise ValueError('Explicit boost-excluded background power required')
    return {'background_kw': float(value)}


def window(runtime, house, now):
    """No device access. An uncertain owned start/release remains a reservation."""
    cfg = configuration(house)
    if cfg is None:
        return None
    water = (house.get('heat_pump') or {}).get('hot_water_control') or {}
    if water.get('enabled') is not True:
        return None
    result = {'background_kw': cfg['background_kw'], 'window': None}
    cycle = runtime.controller.state if runtime.controller is not None else {}
    if cycle.get('phase') not in {'planned', 'start_pending', 'active', 'release_pending'}:
        return result
    power = (water.get('comfort_policy') or {}).get('electrical_power_kw')
    if type(power) not in (int, float) or not math.isfinite(power) or not 0 < power <= 30:
        raise ValueError('Explicit hot-water electrical load model required')
    start = max(float(cycle['start']), now)
    end = min(float(cycle['end']), float(cycle['deadline']))
    if cycle.get('attempted_at') is not None:
        end = min(end, cycle['attempted_at'] + cycle['max_runtime_s'])
    if start < end:
        result['window'] = {'start': start, 'end': end, 'power_kw': power}
    return result


def identity(reservation):
    if reservation is None:
        return None
    w = reservation['window']
    # Current time moves within a quarter; do not replan on every loop.
    return (reservation['background_kw'], None if w is None else (w['end'], w['power_kw'],
            int(w['start'] // 900)))


def off_profile(engine, now):
    """Unknown/old boost states are excluded, not reclassified as heating-free.

    Uses the existing household-load boundary, excludes separately planned EVs,
    and learns only periods with a fresh, explicit inactive boost receipt.
    """
    from sqlalchemy import text
    import battery_learning
    try:
        with engine.connect() as c:
            rows = c.execute(text(local_sql("""
                SELECT extract(isodow FROM h)::int - 1, extract(hour FROM h)::int, kw
                FROM (
                    SELECT date_trunc('hour', timestamp AT TIME ZONE __EW_TIMEZONE__) h,
                      avg(GREATEST(0, house_consumption_w / 1000.0
                          - COALESCE(ev_power_kw,0) - COALESCE(ev_carport_power_kw,0))) kw
                    FROM sensor_log
                    WHERE timestamp >= :start AND timestamp <= :finish
                      AND house_consumption_w IS NOT NULL
                      AND hot_water_boost_active IS FALSE
                      AND hot_water_boost_sample_at BETWEEN extract(epoch FROM timestamp)-90
                                                          AND extract(epoch FROM timestamp)+5
                    GROUP BY 1 HAVING count(*) >= 30
                ) samples
            """)), {'start': now-timedelta(days=28), 'finish': now}).fetchall()
        return battery_learning.median_load_profile(rows)
    except Exception:
        return {}  # Explicit configured background, never the mixed-history profile.


def apply(slots, reservation, profile, now):
    """Replace a mixed total-load forecast; add the scheduled boost exactly once."""
    if reservation is None:
        return slots
    w = reservation['window']
    out = []
    for s in slots:
        if 'hot_water_kw' in s:
            raise ValueError('Hot-water reservation already applied')
        t = s['t']; stamp = t.timestamp()
        base = profile.get((t.weekday(), t.hour), reservation['background_kw'])
        if type(base) not in (int, float) or not math.isfinite(base) or base < 0:
            raise ValueError('Invalid boost-excluded background forecast')
        seconds = max(0, min(stamp+900, w['end'])-max(stamp, now, w['start'])) if w else 0
        power = w['power_kw'] * seconds / 900 if w else 0
        out.append({**s, 'load_kw': base+power, 'hot_water_kw': power, 'background_load_kw': base})
    return out


def boost_fields(points, bindings, resolve, number, received_at):
    """Reuse the same local REST response as the tank reading; never infer off."""
    result = {'hot_water_boost_active': None, 'hot_water_boost_sample_at': None}
    b = bindings.get('hot_water_boost')
    if not isinstance(b, dict):
        return result
    try:
        _, point = resolve(points, b)
        value = number(point)
        if point['metadata']['divisor'] != 1 or value not in (b['start_value'], b['release_value']):
            return result
        result.update(hot_water_boost_active=value == b['start_value'],
                      hot_water_boost_sample_at=datetime.fromisoformat(received_at).timestamp())
    except (KeyError, TypeError, ValueError):
        pass
    return result
