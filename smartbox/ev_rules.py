"""Per bil: får den ladda från köpt el, och finns det ett maxpris? (#427, #429, del av Emlbens förslag #420)

Sparas i ew_settings som ev_rules = {bil-id: {"grid": true/false, "max_price": kr/kWh eller null}}.
  - grid = false ("bara sol"): ingen planerad laddning från nätet, inte heller morgongolvet. Solladdning och
    "Ladda nu" (ett uttryckligt val) fungerar som vanligt.
  - max_price: planerade kvartar dyrare än så tas bort. Morgongolvet (50 % kl 06, en säkerhet) undantas.
Priset jämförs med spotpriset i samma skala som EnergyWizards prisgraf (elpriser-tabellen).
"""

DEFAULT = {"grid": True, "max_price": None}


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
    return out


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
    return _clean(rule), None
