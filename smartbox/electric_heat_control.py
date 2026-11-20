"""Prisstyrning av elvärme med egen termostat (#431).

Av tills electric_heat.enabled är true. Varje zon är en climate-entitet med
lägsta och högsta börvärde. Dyrt blir lägsta, billigt och kraftigt
solöverskott blir högsta, med samma hysteres som värmepumpens grundläge.
Ett schema går före priset. Bortaläge går före schemat och sätter lägsta.
Sommarläge lagrar inte värme: billigt och solöverskott ger också lägsta,
schemat gäller ändå.

control måste vara true för att något ska skrivas. Annars loggas börvärdet
som en skuggåtgärd. Saknat pris, prisreserv (gårdagens profil) eller gråzon
utan tidigare läge lämnar börvärdet orört. Effekten, när en givare finns,
förklaras i lastnedbrytningen. Effekttaket ser redan samma watt på elmätaren.
"""
import math
import re
from datetime import datetime

_CLIMATE = re.compile(r"climate\.[a-z0-9_]{1,128}\Z")
_POWER = re.compile(r"sensor\.[a-z0-9_]{1,128}\Z")
_CLOCK = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\Z")
SOLAR_SURPLUS_W = -1500
DEADBAND_C = 0.2
_MIN_C, _MAX_C = 5.0, 35.0


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clock(value):
    match = _CLOCK.fullmatch(str(value or "").strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _window(item):
    if not isinstance(item, dict):
        return None
    start, end = _clock(item.get("start")), _clock(item.get("end"))
    temp = item.get("temp_c")
    days = item.get("days")
    if start is None or end is None or start == end or not _finite(temp):
        return None
    if days is None:
        days = list(range(7))
    if not isinstance(days, list) or not days or any(not isinstance(d, int) or isinstance(d, bool) or d < 0 or d > 6 for d in days):
        return None
    return {"start": start, "end": end, "temp_c": float(temp), "days": set(days)}


def _covers(window, now):
    if now.weekday() not in window["days"]:
        return False
    minute = now.hour * 60 + now.minute
    if window["start"] < window["end"]:
        return window["start"] <= minute < window["end"]
    return minute >= window["start"] or minute < window["end"]


def zones(config):
    """Giltiga zoner. Ogiltiga poster hoppas över, motorn fortsätter."""
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return []
    raw = config.get("zones")
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw:
        if len(out) >= 16 or not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "")
        if not _CLIMATE.fullmatch(entity) or entity in seen:
            continue
        low, high = item.get("min_c"), item.get("max_c")
        if not _finite(low) or not _finite(high) or not _MIN_C <= float(low) < float(high) <= _MAX_C:
            continue
        power = item.get("power")
        power = str(power) if isinstance(power, str) and _POWER.fullmatch(power) else None
        name = str(item.get("name") or entity).strip().replace("\n", " ")[:40] or entity
        schedule = [w for w in (_window(x) for x in (item.get("schedule") or [])) if w]
        seen.add(entity)
        out.append({"entity": entity, "name": name, "min_c": float(low), "max_c": float(high),
                    "power": power, "schedule": schedule})
    return out


def loads(config):
    """Effekten som lastnedbrytningen får förklara. Samma givare räknas en gång."""
    out, seen = [], set()
    for zone in zones(config):
        if not zone["power"] or zone["power"] in seen:
            continue
        seen.add(zone["power"])
        out.append({"name": zone["name"], "entities": [zone["power"]]})
    return out


def _clamp(zone, temp):
    return min(zone["max_c"], max(zone["min_c"], temp))


def target_for(zone, now, mode, solar, summer, away):
    """(börvärde, orsak) eller (None, None) när inget ska ändras."""
    if not isinstance(now, datetime):
        return None, None
    if away:
        return zone["min_c"], "borta"
    for window in zone["schedule"]:
        if _covers(window, now):
            return _clamp(zone, window["temp_c"]), "schema"
    if mode not in ("CHEAP", "EXPENSIVE"):
        return None, None
    if summer:
        return zone["min_c"], "sommar"
    if solar and mode == "EXPENSIVE":
        return zone["max_c"], "solöverskott"
    if mode == "CHEAP":
        return zone["max_c"], "billigt"
    return zone["min_c"], "dyrt"


class Controller:
    def __init__(self, config):
        self.zones = zones(config)
        self.control = isinstance(config, dict) and config.get("control") is True and bool(self.zones)
        self.mode = None

    def _mode(self, price, limit, hysteresis):
        if not _finite(price) or not _finite(limit):
            return None
        hyst = hysteresis if _finite(hysteresis) and hysteresis >= 0 else 0.10
        if price <= limit - hyst:
            self.mode = "CHEAP"
        elif price >= limit + hyst:
            self.mode = "EXPENSIVE"
        return self.mode

    def tick(self, now, price, limit, hysteresis, avg_net, summer, away, fallback, read, write, record, shadow):
        """read(entity) -> börvärde eller None. write och record anropas bara vid en verklig skillnad."""
        if not self.zones or fallback:
            return []
        mode = self._mode(price, limit, hysteresis)
        solar = _finite(avg_net) and avg_net < SOLAR_SURPLUS_W
        done = []
        for zone in self.zones:
            target, reason = target_for(zone, now, mode, solar, bool(summer), bool(away))
            if target is None:
                continue
            try:
                current = read(zone["entity"])
            except Exception:
                current = None
            if _finite(current) and abs(float(current) - target) < DEADBAND_C:
                continue
            detail = f"{zone['entity']} {target:.1f} °C ({reason})"
            if self.control and not shadow:
                try:
                    write(zone["entity"], target)
                except Exception:
                    continue
            else:
                record("Elvärme", detail)
            done.append(detail)
        return done
