"""Ordningen för solöverskottet (#430, del av Emlbens förslag #420): husbatteri, elbil, spabad, varmvatten, hus.

Sparas i ew_settings som solar_order = ["battery", "ev", "spa", "hotwater", "house"] (standard = det inbyggda
beteendet: batteriet laddar till sin prioritetsnivå, sedan elbilen, spabadet, varmvattnet och huset).

Regel: en last längre ned får bara STARTA på överskott när ingen last högre upp vill ha det och skulle kunna starta på
samma överskott. En högre last som redan går tar sin del; det som blir över (syns i mätaren) får nästa använda. En
högre last som nyss startat får JUST_STARTED på sig innan mätaren räknas som uppdaterad - annars kunde två laster starta
samma minut på samma överskott.

Husbatteriet regleras av sin egen styrning (battery_control): står elbilen eller en annan last före batteriet och vill
ha överskottet, vilar batteriet så att överskottet når lasten.
"""
from datetime import timedelta

LOADS = ("battery", "ev", "spa", "hotwater", "house")
DEFAULT = list(LOADS)
NAMES = {"battery": "Husbatteri", "ev": "Elbil", "spa": "Spabad", "hotwater": "Varmvatten", "house": "Huset"}
JUST_STARTED = timedelta(minutes=5)


def normalize(raw) -> list:
    """Giltig ordning med alla laster precis en gång; okända tas bort, saknade läggs sist i standardordning."""
    out = [x for x in (raw or []) if x in LOADS]
    out = list(dict.fromkeys(out))
    return out + [x for x in DEFAULT if x not in out]


def before(order, a, b) -> bool:
    o = normalize(order)
    return o.index(a) < o.index(b)


def blocker(load, order, info, surplus_w, now):
    """Den högre last som ska få överskottet före `load`, eller None om `load` får starta.
    info[x] = {"wants": bool, "active": bool, "since": datetime|None, "min_w": W som krävs för att starta}."""
    o = normalize(order)
    for h in o[:o.index(load)]:
        i = info.get(h) or {}
        if not i.get("wants"):
            continue
        if i.get("active"):
            since = i.get("since")
            if since is not None and now - since < JUST_STARTED:
                return h                        # nyss startad: mätaren visar inte dess förbrukning än
            continue                            # går redan - det som blir över får nästa ta
        if surplus_w >= float(i.get("min_w") or 0):
            return h                            # vill ha och kan starta på det här överskottet
    return None
