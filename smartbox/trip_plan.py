"""Resplan: ett engångsmål för en bil - klar till ett klockslag idag eller imorgon, med en laddnivå.

Appens knapp "Resplan" har funnits sedan första versionen men anropade en funktion som aldrig byggdes (genomlysningen
2026-11-15). Målet sparas som överstyrningen <bil>_trip = "<ISO-tid>|<soc>" och används av laddplanen som "klar senast"
(samma väg som #200:s HA-entitet). Det går ut av sig självt när tiden passerat; veckoschemat ändras inte.
"""
from datetime import datetime, timedelta


def encode(when: datetime, soc: int) -> str:
    return f"{when.isoformat()}|{int(soc)}"


def parse(value, now: datetime):
    """(klar senast, mål %) om resplanen ligger framåt i tiden, annars None."""
    if not value or "|" not in str(value):
        return None
    t, _, s = str(value).partition("|")
    try:
        when = datetime.fromisoformat(t)
        soc = max(20, min(100, int(float(s))))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None and now.tzinfo is not None:
        when = when.replace(tzinfo=now.tzinfo)
    return (when, soc) if when > now else None


def make(now: datetime, day: int, hhmm: str, soc) -> datetime:
    """Tiden för en resplan: day 0 = idag, 1 = imorgon. Ett klockslag idag som redan passerat räknas som imorgon."""
    h, m = (int(x) for x in str(hhmm).split(":")[:2])
    when = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1 if int(day) == 1 else 0)
    if when <= now:
        when += timedelta(days=1)
    return when
