"""spa_error_watch.py - säg till när spabadet rapporterar ett NYTT fel (Gecko: sensor.<bad>_error_s, spa.entities.error).

Sensorn visar felkoden som text ("OverTemp"). Vissa integrationer nollställer den inte av sig själva, så ett gammalt fel kan
stå kvar i dagar. Därför: första gången vi ser sensorn sparas värdet utan notis (vi vet inte om det är nytt), och därefter
skickas bara en notis när värdet ÄNDRAS till ett annat fel. Tillbaka till "inget fel" nollställer, så att samma fel kan komma
igen och då meddelas. Ren logik; sparat värde i ew_settings (spa_error_seen).
"""
_OK = {"", "none", "no error", "no errors", "no problem", "ok", "off", "false", "0", "normal", "unknown", "unavailable"}
KEY = "spa_error_seen"


def is_error(text) -> bool:
    return str(text if text is not None else "").strip().lower() not in _OK


def step(text, seen):
    """(nytt sparat värde, text att meddela eller None). seen: tidigare sparat värde (None = aldrig sett).
    Otillgänglig/okänd sensor ändrar ingenting (en omstart av HA ska varken nollställa eller larma)."""
    raw = str(text).strip() if text is not None else ""
    if raw.lower() in ("unavailable", "unknown", ""):
        return seen, None
    cur = raw if is_error(raw) else ""
    if seen is None:
        return cur, None                        # första avläsningen: gammalt eller nytt vet vi inte
    if cur and cur != seen:
        return cur, raw
    return cur, None
