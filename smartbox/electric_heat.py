"""#431: elvärme med egen termostat (Adax, golvvärme, element).

Värmepumpens läge (billigt eller dyrt) väljer elementets egna golv eller tak.
En valfri effektgivare (power_w) läses och räknas i lastnedbrytningen, så att
elementet inte ser ut som oförklarad last. Ingenting skrivs till climate-entiteten,
varken i skuggläge eller i vanlig drift.
"""
import json
import math
import re

_ENTITY = re.compile(r"climate\.[a-z0-9_]{1,128}\Z")
_SENSOR = re.compile(r"sensor\.[a-z0-9_]{1,128}\Z")


def plan(cfg, pump_mode, read=None):
    """Rader till beslutsloggen. cfg är electric_heat ur installationen, eller None.

    read(entity) ger effekt i watt. Saknas den, eller givaren, uteblir wattalet.
    """
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return []
    if pump_mode not in ("CHEAP", "EXPENSIVE"):
        return []
    heaters = cfg.get("heaters")
    if not isinstance(heaters, list):
        return []
    lines, seen = [], set()
    for heater in heaters:
        if not isinstance(heater, dict):
            continue
        entity = heater.get("entity")
        if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
            continue
        line = _one(heater, pump_mode, _reading(heater, read, seen))
        if line:
            lines.append(line)
    return lines


def measured(cfg, read):
    """Förklarad last till lastnedbrytningen: [{"name", "w"}]. Tom när listan är av."""
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True or not callable(read):
        return []
    heaters = cfg.get("heaters")
    if not isinstance(heaters, list):
        return []
    rows, seen = [], set()
    for heater in heaters:
        if not isinstance(heater, dict):
            continue
        entity = heater.get("entity")
        if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
            continue
        watts = _reading(heater, read, seen)
        if watts is None:
            continue
        rows.append({"name": _label(heater, entity)[:40], "w": round(watts)})
    return rows


def _sensors(heater):
    raw = heater.get("power_w") if isinstance(heater, dict) else None
    items = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    out = []
    for item in items:
        if isinstance(item, str) and _SENSOR.fullmatch(item) and item not in out:
            out.append(item)
    return out


def _reading(heater, read, seen):
    if not callable(read):
        return None
    sensors = [sensor for sensor in _sensors(heater) if sensor not in seen]
    if not sensors:
        return None
    vals = []
    for sensor in sensors:
        seen.add(sensor)
        try:
            value = read(sensor)
        except Exception:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if math.isfinite(value):
            vals.append(value)
    if not vals:
        return None
    return max(0.0, sum(vals))


def _one(heater, pump_mode, watts=None):
    if not isinstance(heater, dict):
        return None
    entity = heater.get("entity")
    if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
        return None
    try:
        low = float(heater.get("min_c"))
        high = float(heater.get("max_c"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(low) and math.isfinite(high) and 5 <= low < high <= 35):
        return None
    target = high if pump_mode == "CHEAP" else low
    why = "billig el" if pump_mode == "CHEAP" else "dyr el"
    label = _label(heater, entity)
    load = f"Drar {round(watts):.0f} W. " if watts is not None else ""
    return (f"🔌 Prio 5c (ELVÄRME, skugga): {label} skulle sättas till {target:.1f} °C ({why}). "
            f"{load}Ingenting skickas ({entity}).")


def _label(heater, entity):
    name = heater.get("name")
    label = name.strip() if isinstance(name, str) and name.strip() else entity
    return " ".join(label.split())[:80]


def comment_block(radiators):
    """Avstängd lista i den nedladdade konfigurationen. Tom om inget element är giltigt."""
    rows = []
    for radiator in radiators or []:
        if not isinstance(radiator, dict):
            continue
        entity = radiator.get("entity")
        if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
            continue
        name = radiator.get("name") if isinstance(radiator.get("name"), str) else ""
        rows.append((" ".join(name.split())[:80], entity))
    if not rows:
        return []
    lines = [
        "# Elvärme (#431). Listan är av. Sätt enabled: true för att se börvärdet i besluten.",
        "# EnergyWizard skriver inte till elementen. power_w (en sensor eller en lista) räknas i lastnedbrytningen.",
        "# electric_heat:",
        "#   enabled: true",
        "#   heaters:",
    ]
    for name, entity in rows:
        lines.append(f"#     - name: {json.dumps(name or entity, ensure_ascii=False)}")
        lines.append(f"#       entity: {entity}")
        lines.append("#       min_c: 16")
        lines.append("#       max_c: 21")
    return lines
