"""Innetemperaturen när de valda rumsgivarna tillfälligt saknas.

2026-11-15: sju gånger på två dygn saknades alla rumsgivare under en minut, och styrningen tog då värmepumpens egen
innegivare. På en Thermia via Husdata är den ett fast värde (20,0 °C), så rumsåterkopplingen (Prio 5b) såg huset "nära
golvet" och höjde börvärdet i onödan. Nu behålls det senaste giltiga värdet från givarna i HOLD; först därefter används
pumpens värde (och larmet om tystnade givare går som förut efter 15 minuter).
"""
from datetime import timedelta

HOLD = timedelta(minutes=15)


def choose(sensor_temp, pump_temp, have_sensors, last_temp, last_at, now):
    """Returnerar (innetemp, källa). sensor_temp = medel/median av givarna nu (None om ingen svarar)."""
    if sensor_temp is not None:
        return sensor_temp, "givare"
    if have_sensors and last_temp is not None and last_at is not None and now - last_at <= HOLD:
        return last_temp, "givare (senaste)"
    return pump_temp, "pump" if pump_temp is not None else None
