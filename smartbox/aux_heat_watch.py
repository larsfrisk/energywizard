"""aux_heat_watch.py - säg till när värmepumpen kört på tillsats (elpatron).

Pumpen har två räknare för tillsatsdrift (aux_runtime_h, aux_runtime_2_h, Husdata-register 35/36). Ökar någon av dem har
tillsatsen gått sedan förra avläsningen. Räknaren tickar i hela timmar (eller den enhet pumpen anger), så notisen kommer när
räknaren stiger, inte i samma sekund tillsatsen kopplas in. Första avläsningen sparas utan notis, och en minskning
(nollställd räknare) sparas utan notis. Ren logik; sparat värde i ew_settings (aux_heat_seen).
"""
KEY = "aux_heat_seen"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def step(a1, a2, seen):
    """(nytt sparat värde [a1, a2], ökning [d1, d2] eller None). Saknad avläsning ändrar ingenting."""
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


def message(inc, dm=None, price=None):
    tot = sum(inc)
    t = f"{tot:g}".replace(".", ",")
    s = (f"Värmepumpen har kört på tillsats (elpatron) i {t} h sedan förra kontrollen.")
    if dm is not None:
        s += f" Gradminuter just nu: {dm:.0f}."
    if price is not None:
        s += f" Elpris: {price:.2f} kr/kWh."
    return s + " Tillsatsen är dyr el, kolla Värmepump i appen."
