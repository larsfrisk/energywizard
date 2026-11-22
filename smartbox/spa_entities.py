"""spa_entities.py - Gecko-spabadets entiteter ur Home Assistants entiteter (#570).

HA:s Gecko-integration ger ett bad flera entiteter med samma namnstam: climate.<bad>_heater (måltemperaturen och, som
attribut, vattnets temperatur), sensor.<bad>_current_temperature, sensor.<bad>_target_temperature, water_heater.<bad>_heater
och switch.<bad>_economy_mode. Upptäckten kopplade förut bara en av dem (climate-entiteten som "temperatur") och drivrutinen
behöver flera, så ett bad som upptäcktes automatiskt visade ingen temperatur och gick inte att styra.

complete_gecko() fyller i det som saknas ur HA:s entiteter via namnstammen, och skriver aldrig över något som redan är valt
(en användares egen konfiguration vinner). Ren logik, testas i tests/test_spa_entities.py. Entiteter EnergyWizard själv
publicerar (smartbox_*, energywizard_*) är aldrig kandidater: de är vår egen utdata, inte badets."""
from __future__ import annotations

import re

_STEM_SUFFIX = re.compile(r"_(heater|climate|thermostat|water_heater)$")
_CURRENT = re.compile(r"(current|water|actual).*temp|^temp(erature)?$|aktuell|vattentemp", re.I)
_TARGET = re.compile(r"(target|set_?point|desired).*temp|^target|^set_?point|mål ?temp|börvärde", re.I)
_ECONOMY = re.compile(r"econom|^eco(_|$)|ekonomi", re.I)
OWN_PREFIXES = ("smartbox_", "energywizard_")


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in (entity_id or "") else ""


def object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1] if "." in (entity_id or "") else (entity_id or "")


def is_own(entity_id: str) -> bool:
    """EnergyWizards egna publicerade entiteter (de får aldrig väljas som en källa)."""
    return object_id(entity_id).startswith(OWN_PREFIXES)


def _without_own(value):
    """EnergyWizards egna entiteter tas bort ur en konfiguration (en sträng eller en lista): en äldre upptäckt kan ha valt
    sensor.smartbox_effekt_spa som spabadets effektkälla, och då matas vår egen utdata tillbaka in som indata."""
    if isinstance(value, str):
        return None if is_own(value) else value
    if isinstance(value, list):
        return [v for v in value if not (isinstance(v, str) and is_own(v))]
    return value


def stem_of(entity_id: str) -> str:
    """climate.erik_spa_heater -> erik_spa"""
    return _STEM_SUFFIX.sub("", object_id(entity_id))


def complete_gecko(entities: dict | None, names: dict | None) -> dict:
    """entities: spa.entities (kan vara ofullständig). names: {entity_id: friendly_name} för alla entiteter i HA.
    Returnerar en kopia där climate, current_temp, target_temp, water_heater och economy_mode är ifyllda när de går att
    hitta. En entitet som redan är vald ändras aldrig, utom att en current_temp som är en climate-entitet (en text, inte en
    siffra) ersätts av en riktig temperatursensor om en finns."""
    e = {k: _without_own(v) for k, v in (entities or {}).items()}
    e = {k: v for k, v in e.items() if v not in (None, "", [])}
    names = names or {}
    anchor = e.get("climate") or next((e[k] for k in ("current_temp", "water_heater") if domain_of(e.get(k) or "") in ("climate", "water_heater")), None)
    if not anchor:
        return e
    if not e.get("climate") and domain_of(anchor) == "climate":
        e["climate"] = anchor
    stem = stem_of(anchor)
    if not stem:
        return e
    siblings = [i for i in names if object_id(i).startswith(stem + "_") and not is_own(i)]

    def rest(i: str) -> str:
        return object_id(i)[len(stem) + 1:]

    def pick(domain: str, want: re.Pattern, avoid: re.Pattern | None = None):
        for i in siblings:
            if domain_of(i) != domain:
                continue
            text = f"{rest(i)} {names.get(i) or ''}"
            if avoid and avoid.search(text):
                continue
            if want.search(text):
                return i
        return None

    cur = e.get("current_temp")
    if not cur or domain_of(cur) != "sensor":
        found = pick("sensor", _CURRENT, _TARGET)
        if found:
            e["current_temp"] = found
    if not e.get("target_temp"):
        found = pick("sensor", _TARGET)
        if found:
            e["target_temp"] = found
    if not e.get("water_heater"):
        found = next((i for i in siblings if domain_of(i) == "water_heater"), None)
        if found:
            e["water_heater"] = found
    if not e.get("economy_mode"):
        found = pick("switch", _ECONOMY)
        if found:
            e["economy_mode"] = found
    return e
