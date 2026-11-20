"""#431: elvärme med egen termostat (Adax, golvvärme, element).

Första steget räknar bara. Värmepumpens läge (billigt eller dyrt) väljer elementets
egna golv eller tak. Ingenting skrivs till climate-entiteten, varken i skuggläge
eller i vanlig drift. Beslutsraden säger vad börvärdet skulle bli.
"""
import json
import math
import re

_ENTITY = re.compile(r"climate\.[a-z0-9_]{1,128}\Z")


def plan(cfg, pump_mode):
    """Rader till beslutsloggen. cfg är electric_heat ur installationen, eller None."""
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return []
    if pump_mode not in ("CHEAP", "EXPENSIVE"):
        return []
    heaters = cfg.get("heaters")
    if not isinstance(heaters, list):
        return []
    lines = []
    for heater in heaters:
        line = _one(heater, pump_mode)
        if line:
            lines.append(line)
    return lines


def _one(heater, pump_mode):
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
    name = heater.get("name")
    label = name.strip() if isinstance(name, str) and name.strip() else entity
    label = " ".join(label.split())[:80]
    return (f"🔌 Prio 5c (ELVÄRME, skugga): {label} skulle sättas till {target:.1f} °C ({why}). "
            f"Ingenting skickas ({entity}).")


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
        "# EnergyWizard skriver inte till elementen i det här steget.",
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
