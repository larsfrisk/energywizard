"""aux_heat_watch.py - säg till när värmepumpen går på tillsats (elpatron).

Thermia Diplomat via Husdata H66 visar tillsatsen i realtid: register 26 (Add heat step 1) och 27 (step 2), 0/1, och 31
(Add heat status, procent). En notis skickas när något steg går från av till på, och inte igen förrän båda stegen varit
av i OFF_MIN minuter (annars blir det en notis varje gång tillsatsen kopplar in och ur under samma dygnsdel).

Pumpar utan de registren (pump_data saknar add_heat_1) faller tillbaka på räknarna för tillsatsdrift (aux_runtime_h,
aux_runtime_2_h, Husdata-register 35/36), som tickar i hela timmar. Ren logik; tillstånd i ew_settings.
"""
KEY = "aux_heat_seen"          # räknarnas senast sedda värden [a1, a2]
STATE_KEY = "aux_heat_state"   # {"on": bool, "off_since": epoch|None}
OFF_MIN = 10


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def realtime(add1, add2, state, now_ts):
    """(nytt tillstånd, notis [steg-lista] eller None). Saknade värden ändrar ingenting. Första avläsningen med tillsats
    på räknas som en start (en notis), eftersom vi inte hade något tidigare tillstånd att tvivla på."""
    a1, a2 = _num(add1), _num(add2)
    if a1 is None and a2 is None:
        return state, None
    steps = [i + 1 for i, v in enumerate((a1, a2)) if v and v > 0]
    st = dict(state) if isinstance(state, dict) else {"on": False, "off_since": None}
    if steps:
        notify = None if st.get("on") else steps
        return {"on": True, "off_since": None}, notify
    if st.get("on"):
        since = st.get("off_since") or now_ts
        if now_ts - since >= OFF_MIN * 60:
            return {"on": False, "off_since": None}, None
        return {"on": True, "off_since": since}, None
    return st, None


def step(a1, a2, seen):
    """Reserv: (nytt sparat värde [a1, a2], ökning [d1, d2] eller None) ur räknarna. Saknad avläsning ändrar ingenting."""
    cur = [_num(a1), _num(a2)]
    if cur[0] is None and cur[1] is None:
        return seen, None
    if not isinstance(seen, (list, tuple)) or len(seen) != 2:
        return cur, None
    new, inc = [], [0.0, 0.0]
    for i in (0, 1):
        old = _num(seen[i])
        if cur[i] is None:
            new.append(seen[i])
        else:
            new.append(cur[i])
            if old is not None and cur[i] > old:
                inc[i] = cur[i] - old
    return new, (inc if any(inc) else None)


def message_realtime(steps, pct=None, dm=None, price=None):
    s = "Värmepumpen har kopplat in tillsats (elpatron) " + " och ".join(f"steg {n}" for n in steps) + "."
    if pct is not None:
        s += f" Tillsatsen ligger på {pct:.0f} %."
    if dm is not None:
        s += f" Gradminuter just nu: {dm:.0f}."
    if price is not None:
        s += f" Elpris: {price:.2f} kr/kWh."
    return s + " Tillsatsen är dyr el, kolla Värmepump i appen."


def message(inc, dm=None, price=None):
    tot = sum(inc)
    t = f"{tot:g}".replace(".", ",")
    s = (f"Värmepumpen har kört på tillsats (elpatron) i {t} h sedan förra kontrollen.")
    if dm is not None:
        s += f" Gradminuter just nu: {dm:.0f}."
    if price is not None:
        s += f" Elpris: {price:.2f} kr/kWh."
    return s + " Tillsatsen är dyr el, kolla Värmepump i appen."
