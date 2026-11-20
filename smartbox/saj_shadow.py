"""SAJ H2 som skuggrecept (#395).

Registerbilden är översatt för hand från evcc-io/evcc
``templates/definition/meter/saj-h2.yaml`` (MIT, evcc-io, 6b1f958).
Ingen kod är kopierad. Det här är en loggrad: inga register skrivs och inget
nät anropas.

Mallens standardläge (AppMode 2) används för självförbrukning och håll.
Skillnaden är bara nivån som behålls: lägsta för självförbrukning, högsta
för håll utan urladdning. Laddning från nätet är ett helt dygn på 100 % och
kan därför bara beskrivas när beslutet vill ha hela märkeffekten. En delad
effekt, urladdning eller vila ger ingen rad.
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
        return "SAJ skugga: självförbrukning, register 13895 = 2 och 13905 = lägsta nivå. Skriver inte."
    if intent == "hold" and power_w is None:
        return "SAJ skugga: håller utan urladdning, register 13895 = 2 och 13905 = högsta nivå. Skriver inte."
    asked = _watts(power_w)
    rating = _watts(cfg.get("max_power_w"))
    charge = _limit(cfg, "max_charge_w")
    if intent == "charge" and asked is not None and rating is not None and asked == rating and asked == charge:
        return ("SAJ skugga: laddar från nätet på hela effekten, register 13895 = 1, 13828 = 1, "
                "13830 = 0, 13831 = 23:59 och 13832 = 100 %. Skriver inte.")
    return None


def observation(recipe, state, cfg):
    """Vad samarbetsläget skulle ha valt. Styrläge och andra recept ger ingen rad."""
    try:
        if recipe != "saj_h2" or not isinstance(cfg, dict) or cfg.get("control") != "samarbete":
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
