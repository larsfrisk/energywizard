"""Filtercykel för spabadet (#447).

Cirkulationen styrs av badets egna cykler och drar några kWh per dygn även
när värmaren vilar. Av tills spa.filter.enabled är true.

Dyrt, och dagens cirkulation redan har nått min_minutes: vila.
Billigt, och dygnets mål inte är nått: kör.
Värmaren igång, ett pågående bad eller ett bad inom bath_hold_minutes
lämnar cykeln orörd. Utan switch, eller med control false, skrivs inget.
Då loggas rådet som skugga. Byten tidigast var dwell_minutes.
"""
import math
import re

_SWITCH = re.compile(r"switch\.[a-z0-9_]{1,128}\Z")
_SIGNALS = ("circ_pump", "filter_switch", "filter", "circulation")
_ON = {"on", "true", "heating", "1"}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _minutes(raw, key, default, lo, hi):
    value = raw.get(key, default)
    if not _finite(value):
        return default
    return int(min(hi, max(lo, float(value))))


def settings(raw):
    """Giltig policy, eller None när filtercykeln är av."""
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None
    switch = raw.get("switch")
    switch = str(switch) if isinstance(switch, str) and _SWITCH.fullmatch(switch) else None
    minimum = _minutes(raw, "min_minutes", 120, 0, 24 * 60)
    daily = max(minimum, _minutes(raw, "daily_minutes", 240, 0, 24 * 60))
    return {
        "control": raw.get("control") is True and switch is not None,
        "switch": switch,
        "min_minutes": minimum,
        "daily_minutes": daily,
        "bath_hold_minutes": _minutes(raw, "bath_hold_minutes", 180, 0, 24 * 60),
        "dwell_minutes": _minutes(raw, "dwell_minutes", 30, 5, 240),
    }


def _truthy(value):
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in _ON


def circulating(activities):
    """True/False när en filter- eller cirkulationssignal finns, annars None."""
    if not isinstance(activities, dict):
        return None
    seen = False
    on = False
    for key in _SIGNALS:
        if key not in activities:
            continue
        seen = True
        on = on or _truthy(activities.get(key))
    return on if seen else None


def heating(activities, heater_state):
    if isinstance(activities, dict) and _truthy(activities.get("heating")):
        return True
    return str(heater_state or "").strip().lower() in ("heating", "heat")


def advise(now, price_mode, on, *, heating_now, in_bath, bath_at, minutes_today, cfg):
    """('kör'|'vila'|None, förklaring). on är True/False/None."""
    if heating_now:
        return None, "värmaren går"
    if in_bath:
        return None, "bad pågår"
    if bath_at is not None:
        try:
            wait = (bath_at - now).total_seconds()
        except TypeError:
            wait = None
        if wait is not None and 0 <= wait <= cfg["bath_hold_minutes"] * 60:
            return None, "bad inom kort"
    if on is None or price_mode not in ("CHEAP", "EXPENSIVE"):
        return None, "ingen avläst cykel" if on is None else "okänt prisläge"
    if price_mode == "EXPENSIVE" and on and minutes_today >= cfg["min_minutes"]:
        return "vila", f"dyr el och cirkulationen har redan gått {minutes_today:.0f} min idag"
    if price_mode == "CHEAP" and not on and minutes_today < cfg["daily_minutes"]:
        return "kör", (f"billig el och cirkulationen har gått {minutes_today:.0f} min "
                       f"av {cfg['daily_minutes']}")
    return None, "cykeln får vara"


class Policy:
    def __init__(self, raw):
        self.cfg = settings(raw)
        self.day = None
        self.minutes = 0.0
        self.expensive_minutes = 0.0
        self.wh = 0.0
        self._prev = None
        self._last_write = None

    @property
    def enabled(self):
        return self.cfg is not None

    @property
    def control(self):
        return bool(self.cfg and self.cfg["control"])

    def _observe(self, now, on, price_mode, power_w, heat):
        day = now.date()
        if self.day != day:
            self.day = day
            self.minutes = 0.0
            self.expensive_minutes = 0.0
            self.wh = 0.0
            self._prev = None
        if self._prev is not None:
            was_on, prev = self._prev
            delta = (now - prev).total_seconds() / 60.0
            if was_on and 0 < delta <= 2:
                self.minutes += delta
                if price_mode == "EXPENSIVE":
                    self.expensive_minutes += delta
                if (not heat and _finite(power_w) and power_w >= 0):
                    self.wh += float(power_w) * delta / 60.0
        self._prev = (bool(on), now)

    def tick(self, now, price_mode, activities, heater_state, in_bath, bath_at, power_w,
             write, record, shadow_on):
        if not self.enabled:
            return None
        heat = heating(activities, heater_state)
        on = circulating(activities)
        self._observe(now, on is True, price_mode, power_w, heat)
        action, _why = advise(
            now, price_mode, on, heating_now=heat, in_bath=in_bath, bath_at=bath_at,
            minutes_today=self.minutes, cfg=self.cfg)
        if action is None:
            return None
        # Texten hålls stadig så skuggläget inte skriver en ny rad varje minut.
        detail = f"{action}: {'dyr el' if action == 'vila' else 'billig el'}"
        if self.wh >= 100:
            detail += f", cirka {self.wh / 1000:.1f} kWh utan värmaren"
        want_on = action == "kör"
        if self.control and not shadow_on and on is not None and on != want_on:
            dwell = self.cfg["dwell_minutes"] * 60
            if self._last_write is None or (now - self._last_write).total_seconds() >= dwell:
                if write(self.cfg["switch"], want_on):
                    self._last_write = now
                    print(f"🛁 Spabad filter: {_why}")
            return detail
        record("spabadets filtercykel", detail)
        return detail
