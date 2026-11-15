"""Per bil: får den ladda från köpt el, och finns det ett maxpris? (#427, #429, del av Emlbens förslag #420)

Sparas i ew_settings som ev_rules = {bil-id: {"grid": true/false, "max_price": kr/kWh eller null}}.
  - grid = false ("bara sol"): ingen planerad laddning från nätet, inte heller morgongolvet. Solladdning och
    "Ladda nu" (ett uttryckligt val) fungerar som vanligt.
  - max_price: planerade kvartar dyrare än så tas bort. Morgongolvet (50 % kl 06, en säkerhet) undantas.
Priset jämförs med spotpriset i samma skala som EnergyWizards prisgraf (elpriser-tabellen).

#426 (också #420): mål utan klar-tid.
  - open_soc: laddmål i % utan klar-tid. Gäller när veckoschemat inte har något påslaget mål. Planen räknar över alla
    kända priser (även morgondagens när de publicerats) men högst max_wait_h timmar framåt.
  - floor_soc: morgongolvet för bilen (standard 50 % kl 06, 0 = av). Med ett mål på 50 % och golvet på 50 % blir det
    alltid laddning före 06 - därför går golvet att sänka eller stänga av per bil.
"""
from datetime import timedelta

FLOOR_DEFAULT = 50
DEFAULT = {"grid": True, "max_price": None, "open_soc": None, "max_wait_h": 36, "floor_soc": FLOOR_DEFAULT}


def _clean(rule) -> dict:
    out = dict(DEFAULT)
    if isinstance(rule, dict):
        if "grid" in rule:
            out["grid"] = bool(rule["grid"])
        mp = rule.get("max_price")
        try:
            mp = None if mp in (None, "") else float(mp)
        except (TypeError, ValueError):
            mp = None
        out["max_price"] = mp if mp is None or mp >= 0 else None
        out["open_soc"] = _num(rule.get("open_soc"), None, 20, 100)
        out["max_wait_h"] = _num(rule.get("max_wait_h"), 36, 6, 72)
        out["floor_soc"] = _num(rule.get("floor_soc"), FLOOR_DEFAULT, 0, 50)
    return out


def _num(v, default, lo, hi):
    try:
        v = None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default
    if v is None:
        return default
    return min(max(v, lo), hi)


def open_until(now, max_wait_h, last_price_end=None):
    """Hur långt fram ett mål utan klar-tid planeras: till sista kända priset, högst max_wait_h timmar fram."""
    cap = now + timedelta(hours=float(max_wait_h or 36))
    if last_price_end is None:
        last_price_end = _last_price_end(now)
    if last_price_end is None:
        return cap
    return min(cap, last_price_end)


def _last_price_end(now):
    try:
        import logger
        with logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT MAX(time_start) AT TIME ZONE 'Europe/Stockholm' FROM elpriser WHERE time_start > now()")
            r = cur.fetchone()
        if r and r[0]:
            t = r[0] + timedelta(minutes=15)
            return t.replace(tzinfo=now.tzinfo) if now.tzinfo else t
    except Exception:
        pass
    return None


def get(car_id, settings=None) -> dict:
    """Regeln för en bil (standard: får ladda från nätet, inget maxpris)."""
    if settings is None:
        try:
            import ew_settings
            settings = ew_settings.load()
        except Exception:
            settings = {}
    return _clean((settings.get("ev_rules") or {}).get(car_id))


def all_rules(car_ids, settings=None) -> dict:
    return {c: get(c, settings) for c in car_ids}


def validate(rule) -> tuple[dict | None, str | None]:
    """För API:t: (ren regel, None) eller (None, felmeddelande)."""
    if not isinstance(rule, dict):
        return None, "Ogiltig regel"
    mp = rule.get("max_price")
    if mp not in (None, ""):
        try:
            mp = float(mp)
        except (TypeError, ValueError):
            return None, "Maxpriset ska vara ett tal"
        if not 0 <= mp <= 20:
            return None, "Maxpriset ska vara 0–20 kr/kWh"
    for key, lo, hi, msg in (("open_soc", 20, 100, "Laddmålet ska vara 20–100 %"), ("max_wait_h", 6, 72, "Väntetiden ska vara 6–72 timmar"),
                             ("floor_soc", 0, 50, "Morgongolvet ska vara 0–50 %")):
        v = rule.get(key)
        if v in (None, ""):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None, msg
        if not lo <= v <= hi:
            return None, msg
    return _clean(rule), None
