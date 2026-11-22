"""spa_bath_learn.py - lär av när man faktiskt badar och föreslå badtider (Emil 2026-11-22).

Ett badtillfälle registreras när spabadets "i bruk"-sensor (spa.entities.in_use) slår till, eller när temperaturen faller snabbt
(samma tolkning som notisen "locket är öppet": minst 1,5 °C på en timme och mer än modellen väntar). Tillfällen inom
GAP_H timmar räknas som ett. Loggen (ew_settings spa_bath_log, lokala tider) sparar de senaste KEEP bad.

Förslaget är badtider i läget "bath" (tider då man badar): per veckodag ett fönster runt de timmar man badat, PAD_BEFORE_H före
första och PAD_AFTER_H efter sista. Det kräver MIN_EVENTS bad, annars sägs det rakt ut att underlaget är för litet. Appen visar
förslaget och fyller i formuläret; inget ändras förrän man trycker Spara. Ren logik, testas i tests/test_spa_bath_learn.py.
"""
from datetime import datetime, timedelta

GAP_H = 4
KEEP = 200
MIN_EVENTS = 3
WEEKS = 12
PAD_BEFORE_H = 2
PAD_AFTER_H = 3
_DAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
_DAYS_ON = ["måndagar", "tisdagar", "onsdagar", "torsdagar", "fredagar", "lördagar", "söndagar"]


def parse(log) -> list:
    out = []
    for s in log or []:
        try:
            out.append(datetime.fromisoformat(str(s)))
        except ValueError:
            pass
    return sorted(out)


def record(log, now: datetime):
    """(ny logg, True om detta var ett nytt badtillfälle). Nya tillfällen inom GAP_H timmar efter det förra är samma bad."""
    ev = parse(log)
    if ev and (now - ev[-1]) < timedelta(hours=GAP_H):
        return [e.isoformat(timespec="minutes") for e in ev][-KEEP:], False
    ev.append(now)
    return [e.isoformat(timespec="minutes") for e in ev][-KEEP:], True


def suggest(log, now: datetime) -> dict:
    """{"n", "text", "windows" (sju {on, from, to} eller None), "mode": "bath"}."""
    since = now - timedelta(weeks=WEEKS)
    ev = [e for e in parse(log) if e >= since]
    n = len(ev)
    if n < MIN_EVENTS:
        return {"n": n, "windows": None, "mode": "bath",
                "text": (f"Hittills {n} bad registrerade. Det behövs minst {MIN_EVENTS} för att föreslå badtider, så fortsätt som vanligt." if n
                         else f"Inga bad registrerade än. Det behövs minst {MIN_EVENTS} för att föreslå badtider.")}
    by = {}
    for e in ev:
        by.setdefault(e.weekday(), []).append(e)
    windows, parts = [], []
    for d in range(7):
        es = by.get(d)
        if not es:
            windows.append({"on": False, "from": "17:00", "to": "21:00"})
            continue
        a = max(0.0, min(e.hour + e.minute / 60 for e in es) - PAD_BEFORE_H)
        b = min(23.99, max(e.hour + e.minute / 60 for e in es) + PAD_AFTER_H)
        f, t = f"{int(a):02d}:{int((a % 1) * 60 // 5 * 5):02d}", f"{int(b):02d}:{int((b % 1) * 60 // 5 * 5):02d}"
        windows.append({"on": True, "from": f, "to": t})
        parts.append(f"{_DAYS_ON[d]} {f}–{t} ({len(es)} bad)")
    first = ev[0].strftime("%-d %b")
    return {"n": n, "windows": windows, "mode": "bath",
            "text": f"Ni har badat {n} gånger sedan {first}. Förslag, tider då ni badar: " + ", ".join(parts) +
                    ". Utanför dem vilar badet på eco-golvet och värms i tid före nästa bad."}
