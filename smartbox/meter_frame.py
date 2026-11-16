"""Explicit coherent DSMR frame contract for HA's change-only sensor cache."""
from datetime import datetime, timedelta, timezone
import math
import re


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset() is None:
        raise ValueError('Dated HA report required')
    return stamp.timestamp()


def dsmr_stamp(value):
    # DSMR's explicit summer/winter suffix disambiguates the repeated DST hour.
    if not isinstance(value, str) or not re.fullmatch(r'\d{12}[SW]', value):
        raise ValueError('Explicit DSMR telegram timestamp required')
    zone = timezone(timedelta(hours=2 if value[-1] == 'S' else 1))
    return datetime.strptime(value[:12], '%y%m%d%H%M%S').replace(tzinfo=zone).timestamp()


def read(entities, states, now):
    """Caller explicitly qualifies all configured roles as one complete telegram.

    A device frame may refresh unchanged cached zero values, never unavailable
    values or mismatched units. No Zenai endpoint, fallback or inferred zero.
    """
    try:
        if entities.get('frame_coherent') is not True:
            return None
        age = entities['max_age_s']
        if type(age) not in (int, float) or not math.isfinite(age) or not 0 < age <= 120:
            return None
        raw = states[entities['frame_timestamp']]
        sample = dsmr_stamp(raw['state'])
        reported = _stamp(raw.get('last_reported') or raw['last_updated'])
        if not 0 <= now-sample <= age or not 0 <= now-reported <= age or abs(reported-sample) > age:
            return None

        def value(role, units, nonnegative=False):
            state = states[entities[role]]
            unit = (state.get('attributes') or {}).get('unit_of_measurement')
            if unit not in units or type(state['state']) is bool:
                raise ValueError('Unexpected meter unit/value')
            number = float(state['state'])
            stamp = _stamp(state.get('last_reported') or state['last_updated'])
            if not math.isfinite(number) or stamp > now or stamp > reported+5 or nonnegative and number < 0:
                raise ValueError('Invalid or mixed-frame measurement')
            return number * (1000 if unit == 'kW' else 1)

        imp, exp = value('import_w', {'W', 'kW'}, True), value('export_w', {'W', 'kW'}, True)
        currents = [value(f'current_l{i}', {'A'}) if entities.get(f'current_l{i}') else None for i in (1,2,3)]
        result = {'net_power_w':imp-exp, 'l1_a':currents[0], 'l2_a':currents[1], 'l3_a':currents[2],
                  'sample_at':sample, 'phase_sample_at':sample if None not in currents else None,
                  'timestamp_basis':'dsmr_frame'}
        for i in (1,2,3):
            if entities.get(f'import_l{i}_w') or entities.get(f'export_l{i}_w'):
                result[f'l{i}_w'] = value(f'import_l{i}_w', {'W','kW'}, True)-value(f'export_l{i}_w', {'W','kW'}, True)
        return result
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None
