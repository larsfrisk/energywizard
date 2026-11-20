"""AlphaESS SMILE som skuggrecept (#395).

Registerbilden är översatt för hand från evcc-io/evcc
``templates/definition/meter/alpha-ess-smile.yaml`` (MIT, evcc-io, 6b1f958).
Ingen kod är kopierad. Det här är en loggrad: inga register skrivs och inget
nät anropas. Dispatchen startas inte och förnyas inte.

Receptet kan bara uttrycka tre lägen:
  självförbrukning: 2176 = 0 (dispatch av)
  håll utan urladdning: 2176 = 1, 2177 = 32000 minus konfigurerad laddeffekt,
  2181 = 1 (bara sol) i 120 s
  laddning från nätet: samma effekt, 2181 = 2 och 2182 i jämna procent
  (0,4 % per steg, 250 = 100 %) i 120 s
Urladdning, en delad effekt, vila och ett udda laddtak ger ingen rad.
"""
import math


def _watts(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    watts = int(round(value))
    if abs(watts - value) > 0.5 or not 1 <= watts <= 100_000:
        return None
    return watts


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    percent = int(round(value))
    if abs(percent - value) > 0.05 or not 0 <= percent <= 100:
        return None
    return percent


def _limit(cfg, key):
    raw = cfg.get(key)
    if raw in (None, ""):
        raw = cfg.get("max_power_w")
    return _watts(raw)


def _soc_bits(cfg):
    """0,4 % per steg. Bara jämna hela procent träffar registret exakt."""
    percent = _percent(cfg.get("max_soc"))
    if percent is None or percent % 2:
        return None
    return percent, (percent * 5) // 2


def describe(intent, power_w, cfg):
    """En mening om läget, eller None när receptet inte täcker just det här."""
    if not isinstance(cfg, dict):
        return None
    if intent == "auto" and power_w is None:
        return "AlphaESS skugga: självförbrukning, register 2176 = 0 (dispatch av). Skriver inte."
    charge = _limit(cfg, "max_charge_w")
    if charge is None:
        return None
    active = 32000 - charge
    if intent == "hold" and power_w is None:
        return (f"AlphaESS skugga: håller utan urladdning, register 2176 = 1, 2177 = {active} "
                f"och 2181 = 1 (bara sol). Varar 120 s. Skriver inte.")
    asked = _watts(power_w)
    soc = _soc_bits(cfg)
    if intent == "charge" and asked is not None and asked == charge and soc is not None:
        percent, bits = soc
        return (f"AlphaESS skugga: laddar från nätet, register 2176 = 1, 2177 = {active}, "
                f"2181 = 2 och 2182 = {bits} ({percent} %). Varar 120 s. Skriver inte.")
    return None


def observation(recipe, state, cfg):
    """Vad samarbetsläget skulle ha valt. Styrläge och andra recept ger ingen rad."""
    try:
        if recipe != "alphaess_smile" or not isinstance(cfg, dict) or cfg.get("control") != "samarbete":
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
