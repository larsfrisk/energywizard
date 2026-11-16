"""Daily operating limits, distinct from the configured maintenance ceiling."""
import math


def resolve(config, overrides=None):
    values = dict(config)
    overrides = overrides or {}
    reserve = float(config.get('reserve_soc', 20))
    maximum = float(config.get('max_soc', 100))
    explicit = ('battery_normal_max_soc' in overrides or
                config.get('normal_ceiling_explicit', config.get('normal_max_soc') is not None))
    normal = overrides.get('battery_normal_max_soc', config.get('normal_max_soc'))
    if 'battery_normal_max_soc' in overrides and normal is None:
        raise ValueError('Explicit normal battery ceiling required')
    buffer = overrides.get('battery_discharge_buffer_soc', config.get('discharge_buffer_soc', 0))
    normal = maximum if normal is None else normal
    for value in (normal, buffer):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Finite battery SOC limits required')
    if not (0 <= reserve < maximum <= 100 and 0 <= buffer <= 20
            and reserve + buffer < normal <= maximum):
        raise ValueError('Battery reserve plus buffer must be below normal ceiling and maintenance maximum')
    values.update(reserve_soc=reserve, max_soc=maximum,
                  normal_max_soc=float(normal), discharge_buffer_soc=float(buffer),
                  discharge_floor_soc=reserve + buffer, normal_ceiling_explicit=explicit)
    return values
