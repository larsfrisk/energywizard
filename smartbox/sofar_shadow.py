"""Sofar HYD G3 som skuggrecept (#395).

Registerbilden är översatt för hand från evcc-io/evcc
``templates/definition/meter/sofarsolar-g3.yaml`` (MIT, evcc-io). Ingen kod är
kopierad. Det här är en loggrad: inga register skrivs och inget nät anropas.
En delad effekt, eller ett läge receptet inte kan uttrycka, ger ingen rad.
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
        return "Sofar skugga: självförbrukning, register 0x1110 = 0. Skriver inte."
    charge = _limit(cfg, "max_charge_w")
    if intent == "hold" and power_w is None and charge is not None:
        return (f"Sofar skugga: håller utan urladdning, register 0x1110 = 3 och 0x1187 "
                f"med min 0 W och max {charge} W. Skriver inte.")
    asked = _watts(power_w)
    if intent == "charge" and asked is not None and asked == charge:
        return (f"Sofar skugga: laddar, register 0x1110 = 3 och 0x1187 med min och max {asked} W. "
                "Skriver inte.")
    discharge = _limit(cfg, "max_discharge_w")
    if intent == "discharge" and asked is not None and asked == discharge:
        return (f"Sofar skugga: laddar ur, register 0x1110 = 3 och 0x1187 med min och max -{asked} W. "
                "Skriver inte.")
    return None


def observation(recipe, state, cfg):
    """Vad samarbetsläget skulle ha valt. Styrläge och andra recept ger ingen rad."""
    try:
        if recipe != "sofar_g3" or not isinstance(cfg, dict) or cfg.get("control") != "samarbete":
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
