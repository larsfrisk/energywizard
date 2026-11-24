"""Kupévärme till ett klockslag (#233).

Motorn läser climate_schedule (en rad per bil: på, tid, temperatur) i main.py.
Den här modulen bara kontrollerar det användaren skickar in. Den skriver inget.
"""
from datetime import datetime

TEMP_MIN = 15.0
TEMP_MAX = 28.0
DEFAULT_TEMP = 21.0
DEFAULT_TIME = "07:00"
HOLD_MAX_MIN = 360          # högst 6 h
HOLD_STEP_MIN = 5
HOLD_REHEAT_BELOW = 1.0     # värm igen när kupén är så här många grader under måltemperaturen


def _on(enabled) -> bool:
    if isinstance(enabled, str):
        return enabled.strip().lower() in ("1", "true", "on", "ja")
    return bool(enabled)


def normalize(enabled, time_s, temp, hold_min=None) -> dict:
    """Tid HH:MM och temperatur 15–28 °C. Ogiltigt värde ger ValueError med en kort svensk mening."""
    raw = str(DEFAULT_TIME if time_s is None else time_s).strip()
    if len(raw) == 8 and raw[2] == ":" and raw[5] == ":":
        raw = raw[:5]
    try:
        datetime.strptime(raw, "%H:%M")
    except ValueError:
        raise ValueError("Ogiltig tid") from None
    if len(raw) != 5:
        raise ValueError("Ogiltig tid")
    try:
        n = float(DEFAULT_TEMP if temp is None or temp == "" else temp)
    except (TypeError, ValueError):
        raise ValueError("Ogiltig temperatur") from None
    if not (TEMP_MIN <= n <= TEMP_MAX):
        raise ValueError("Temperaturen måste ligga mellan 15 och 28 °C")
    try:
        hold = int(float(0 if hold_min is None or hold_min == "" else hold_min))
    except (TypeError, ValueError):
        raise ValueError("Ogiltig hålltid") from None
    if not (0 <= hold <= HOLD_MAX_MIN):
        raise ValueError("Hålltiden måste vara mellan 0 minuter och 6 timmar")
    return {"enabled": _on(enabled), "time": raw, "temp": round(n, 1), "hold_min": hold // HOLD_STEP_MIN * HOLD_STEP_MIN}


def view(row: dict | None, has_climate: bool) -> dict:
    """Raden från settings.get_climate_schedule, plus om bilen har en klimatentitet."""
    row = row or {}
    temp = row.get("target_temp")
    try:
        shown = float(temp) if temp is not None else DEFAULT_TEMP
    except (TypeError, ValueError):
        shown = DEFAULT_TEMP
    return {
        "enabled": bool(row.get("enabled")),
        "time": row.get("target_time") or DEFAULT_TIME,
        "temp": shown,
        "hold_min": int(row.get("hold_min") or 0),
        "has_climate": bool(has_climate),
    }


def hold_window(now, target_hhmm, hold_min):
    """Starten på den pågående hålltiden (senaste klockslaget som passerat, högst hold_min minuter sedan) eller None.
    Räknar både i dag och i går, så en hålltid över midnatt (varm kl 23:30, håll 2 h) fungerar."""
    from datetime import datetime as _dt, timedelta
    if not hold_min or hold_min <= 0:
        return None
    t = _dt.strptime(target_hhmm, "%H:%M").time()
    for back in (0, 1):
        cand = _dt.combine(now.date() - timedelta(days=back), t).replace(tzinfo=now.tzinfo)
        if cand <= now:
            return cand if (now - cand).total_seconds() < hold_min * 60 else None
    return None


def hold_step(state, now, target_hhmm, hold_min, target_temp, c_state, c_temp, is_connected, away):
    """Håll bilen varm efter sluttiden (#598). state är en dict per bil som anroparen behåller mellan varven.
    Returnerar (åtgärd, förklaring): "on" värm, "off" stäng av eller None. Hålltiden avslutas för dagen när bilen
    flyttats (borta från huset) eller när kabeln dragits ur efter att den varit inkopplad - då har föraren hämtat
    bilen. Efter det rör vi inte värmen igen förrän nästa sluttid."""
    start = hold_window(now, target_hhmm, hold_min)
    if start is None:
        return None, None
    key = start.isoformat()
    if state.get("key") != key:
        state.clear()
        state["key"] = key
    if state.get("ended"):
        return None, None
    if is_connected:
        state["was_connected"] = True
    if away or (state.get("was_connected") and not is_connected):
        state["ended"] = True
        return None, "Hålltiden avslutad: bilen är hämtad"
    if c_temp is None:
        return None, None
    if c_state == "off" and c_temp < target_temp - HOLD_REHEAT_BELOW:
        return "on", f"Håller bilen varm efter {target_hhmm}: kupén {c_temp:.0f} °C, värmer mot {target_temp:.0f} °C"
    if c_state != "off" and c_temp >= target_temp:
        return "off", f"Kupén är {c_temp:.0f} °C, stänger av värmen tills den svalnat"
    return None, None
