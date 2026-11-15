"""spa_bath.py - badtider för spabadet (Emil 2026-11-08).

Spabadet hölls varmt dygnet runt, och nattsänkningen gav lite: ett välisolerat bad svalnar bara någon grad och värms
sedan upp igen på morgonen. Med badtider (vilka dagar och tider man brukar bada) får badet ligga på eco-golvet
(spa_low_temp) utanför dem och värms upp inför nästa badtid, på de billigaste timmarna (samma planerare som det
manuella spabadsschemat, decisions.check_spa_schedule_plan).

Inställningen (ew_settings "spa_bath_windows"): sju poster, en per veckodag (0 = måndag):
    [{"on": false}, ..., {"on": true, "from": "10:00", "to": "18:00"}, ...]
Inga påslagna dagar = ingen badtidsstyrning (som förut). Ren logik här; testas i tests/test_spa_bath.py.

Läget "inga bad" (Emil 2026-11-15, ew_settings "spa_bath_mode" = "nobath"): samma sju poster anger i stället när man
INTE badar, t.ex. 22:00-16:00 (natt och arbetsdag; till före från = över midnatt). Under de tiderna får badet svalna,
och planeraren värmer på de billigaste timmarna så att det är varmt när tiden tar slut. Hur långt det sjunker avgörs
av de inlärda modellerna för uppvärmning och avsvalning, inte av en fast gräns. Övrig tid hålls badet varmt.
"""
from datetime import datetime, time, timedelta

PLAN_AHEAD_H = 36          # längre bort än så planeras ingen uppvärmning än (badet ligger kvar på eco-golvet)


def _t(s, default):
    try:
        h, m = (int(x) for x in str(s).split(":")[:2])
        return time(h % 24, m % 60)
    except (TypeError, ValueError):
        return default


def windows(raw, wrap=False) -> list:
    """Normaliserar inställningen till [(veckodag, från, till)] för påslagna dagar. wrap: till före från = över midnatt."""
    out = []
    for day, w in enumerate((raw or [])[:7]):
        if isinstance(w, dict) and w.get("on"):
            a, b = _t(w.get("from"), time(17, 0)), _t(w.get("to"), time(22, 0))
            if b > a or (wrap and b != a):
                out.append((day, a, b))
    return out


def _nobath_intervals(now: datetime, raw):
    """Sammanslagna inga-bad-intervall [(start, slut)] från igår till en vecka fram."""
    iv = []
    for k in range(-1, 8):
        d = (now + timedelta(days=k)).date()
        for day, a, b in windows(raw, wrap=True):
            if d.weekday() != day:
                continue
            start = datetime.combine(d, a, tzinfo=now.tzinfo)
            end = datetime.combine(d + timedelta(days=1 if b <= a else 0), b, tzinfo=now.tzinfo)
            iv.append((start, end))
    iv.sort()
    merged = []
    for s_, e_ in iv:
        if merged and s_ <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e_))
        else:
            merged.append((s_, e_))
    return merged


def status(now: datetime, raw, mode: str = "bath"):
    """(i_badtid, nästa_start, nuvarande_slut). nästa_start = början på nästa badtid inom en vecka (None = inga
    badtider). i_badtid = True mellan från och till en badtidsdag.
    mode "nobath": raw anger tider då man inte badar - all annan tid är badtid."""
    if mode == "nobath":
        iv = _nobath_intervals(now, raw)
        if not iv:
            return False, None, None
        for s_, e_ in iv:
            if s_ <= now < e_:
                return False, e_, None                 # ingen badtid nu: varmt igen när intervallet tar slut
        nxt = next((s_ for s_, _ in iv if s_ > now), None)
        return True, None, nxt                          # badtid nu, till nästa inga-bad-tid
    ws = windows(raw)
    if not ws:
        return False, None, None
    best = None
    for k in range(8):
        d = (now + timedelta(days=k)).date()
        for day, a, b in ws:
            if d.weekday() != day:
                continue
            start = datetime.combine(d, a, tzinfo=now.tzinfo)
            end = datetime.combine(d, b, tzinfo=now.tzinfo)
            if start <= now < end:
                return True, start, end
            if start > now and (best is None or start < best):
                best = start
    return False, best, None


def listing(raw) -> list:
    """Sju poster för gränssnitten (appen och webben): [{"on", "from", "to"}], måndag först."""
    out = []
    for i in range(7):
        w = raw[i] if isinstance(raw, list) and i < len(raw) and isinstance(raw[i], dict) else {}
        out.append({"on": bool(w.get("on")), "from": str(w.get("from") or "17:00")[:5], "to": str(w.get("to") or "21:00")[:5]})
    return out


def clean(rows, mode: str = "bath"):
    """Det gränssnitten skickar -> det som sparas (None = inga badtider). Ogiltiga tider eller till <= från: dagen av
    (i läget "nobath" får till ligga före från = över midnatt)."""
    import re
    if not isinstance(rows, list) or len(rows) != 7:
        raise ValueError("Sju dagar behövs")
    ok = lambda s: bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(s or "")))
    out = []
    for w in rows:
        w = w if isinstance(w, dict) else {}
        a, b = str(w.get("from") or ""), str(w.get("to") or "")
        good = ok(a) and ok(b)
        valid = b > a or (mode == "nobath" and b != a)
        out.append({"on": bool(w.get("on")) and good and valid, "from": a if good else "17:00", "to": b if good else "21:00"})
    return out if any(x["on"] for x in out) else None


def summary(saved, mode: str = "bath") -> str:
    n = sum(1 for w in (saved or []) if w.get("on"))
    if mode == "nobath":
        return (f"Sparat - {n} dagar med tider utan bad. Då får badet svalna och värms på de billigaste timmarna till "
                "badtiden börjar." if n else "Sparat - inga tider utan bad, badet hålls varmt som förut.")
    return (f"Sparat - {n} badtider. Utanför dem får badet svalna till eco-golvet och värms i tid före nästa." if n
            else "Sparat - inga badtider, badet hålls varmt som förut.")
