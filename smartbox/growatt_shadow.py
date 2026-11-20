"""Growatt hybrid som skuggrecept (#395).

Registerbilden är översatt för hand från evcc-io/evcc
``templates/definition/meter/growatt-hybrid.yaml`` (MIT, evcc-io, 6b1f958).
Ingen kod är kopierad. Det här är en loggrad: inga register skrivs och inget
nät anropas. Engångsinställningen av register 1100–1102 görs inte.

Receptet kan bara uttrycka tre lägen, utan effekt:
  självförbrukning: 1102 = 0 och 1092 = 0
  håll utan urladdning: 1102 = 1 och 1092 = 0
  laddning från nätet: 1102 = 1 och 1092 = 1
En delad effekt, urladdning eller vila ger ingen rad.
"""
import math


def _watts(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    watts = int(round(value))
    if abs(watts - value) > 0.5 or not 1 <= watts <= 100_000:
        return None
    return watts


def _limit(cfg, key):
    raw = cfg.get(key)
    if raw in (None, ""):
        raw = cfg.get("max_power_w")
    return _watts(raw)


def describe(intent, power_w, cfg):
    """En mening om läget, eller None när receptet inte täcker just det här."""
    if not isinstance(cfg, dict):
        return None
    if intent == "auto" and power_w is None:
        return "Growatt skugga: självförbrukning, register 1102 = 0 och 1092 = 0. Skriver inte."
    if intent == "hold" and power_w is None:
        return "Growatt skugga: håller utan urladdning, register 1102 = 1 och 1092 = 0. Skriver inte."
    charge = _limit(cfg, "max_charge_w")
    asked = _watts(power_w)
    if intent == "charge" and asked is not None and charge is not None and asked == charge:
        return "Growatt skugga: laddar från nätet, register 1102 = 1 och 1092 = 1. Skriver inte."
    return None


def observation(recipe, state, cfg):
    """Vad samarbetsläget skulle ha valt. Styrläge och andra recept ger ingen rad."""
    try:
        if recipe != "growatt_hybrid" or not isinstance(cfg, dict) or cfg.get("control") != "samarbete":
            return None
        if not isinstance(state, dict):
            return None
        import battery_control
        preview = dict(cfg)
        preview["control"] = "styr"
        preview["standby_for_hold"] = False
        decision = battery_control.decide(
            state, preview, frozenset({"auto", "hold", "idle", "charge", "discharge"}))
        return describe(decision.get("intent"), decision.get("power_w"), preview)
    except Exception:
        return None
