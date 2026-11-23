"""#583: motorns rad om legionella sa "14 dagar passerade -> Tvingande körning" varje varv, med gränsen i stället för
det verkliga antalet dagar, och även i skuggläge där inget kommando skickas. Det såg ut som ett gammalt meddelande
som fastnat. Raden skrivs om efter att gpm räknat klart (gpm.py rörs inte): verkligt antal dagar, temperaturen som
räknas, och i skuggläge att inget skickas. Resten av loggen lämnas orörd."""

_MARK = "(LEGIONELLA): "
_FORCED = "dagar passerade -> Tvingande körning"
NEVER_DAYS = 900.0     # motorn räknar 999 dagar när varmvattnet aldrig mätts på temperaturen


def _fmt(t):
    return f"{float(t):.0f}"


def explain(log, days, leg_max, leg_temp, shadow):
    """Returnerar en ny loggrad-lista där legionellaraden "N dagar passerade -> Tvingande körning till T°C" ersatts."""
    out = []
    for line in log:
        if not (isinstance(line, str) and _MARK in line and _FORCED in line):
            out.append(line)
            continue
        t, m = _fmt(leg_temp), int(leg_max)
        if days is None or days >= NEVER_DAYS:
            head = f"🦠 Prio 7 (LEGIONELLA): Varmvattnet har aldrig mätts på {t}°C sedan start (gräns {m} dagar)"
        else:
            head = (f"🦠 Prio 7 (LEGIONELLA): {int(days)} dagar sedan varmvattnet senast mättes på {t}°C "
                    f"(gräns {m} dagar)")
        if shadow:
            out.append(f"{head} -> Skuggläge, ingen tvingande körning till {t}°C skickas.")
        else:
            out.append(f"{head} -> Tvingande körning till {t}°C.")
    return out
