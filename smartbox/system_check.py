"""system_check.py - del A av "Testa ditt system": läser allt som valts i installationen och säger om det går att lita på.

För varje vald entitet (värmepump, spabad, solceller, batteri, elmätare, elbilar och deras laddboxar, ...) kontrolleras att den
finns i Home Assistant, svarar, har ett värde av rätt slag (tal där tal väntas, rimligt intervall) och är färsk. Dessutom några
sammanhangsregler som fångar kända fallgropar (en laddbox utan effektsensor ger 0 kr i kostnadskortet, #578; en climate-entitet
som temperatur, #570). Inga kommandon skickas. Ren logik utan I/O - testas i tests/test_system_check.py.
"""
import re
from datetime import datetime, timezone

OK, WARN, FAIL = "ok", "warn", "fail"
STALE_MIN = 720                 # äldre än så (12 h) varnar vi för. HA uppdaterar en sensor bara när värdet ändras, så en bil som sover eller
                                # en laddbox som inte laddar står still länge utan att något är fel.
_NO_STATE_DOMAINS = ("button", "scene", "script", "automation")
_FLAG_DOMAINS = ("binary_sensor", "switch", "input_boolean", "light", "fan", "lock", "cover", "update", "device_tracker")   # på/av, aldrig ett tal
_TRACKERS = ("device_tracker", "lock", "cover", "light", "fan", "update")
_LABELS = {
    "indoor_temp": "Innetemperatur", "outdoor_temp": "Utetemperatur", "forward_temp": "Framledning", "return_temp": "Retur",
    "water_temp": "Varmvatten", "degree_minutes": "Gradminuter", "power_w": "Effekt", "power_kw": "Effekt", "current_temp": "Vattentemperatur",
    "target_temp": "Målvärde", "soc": "Laddnivå", "plugged_in": "Inkopplad", "charging": "Laddar", "charging_state": "Laddstatus",
    "status": "Status", "current_a": "Ström", "session_kwh": "Sessionsenergi", "lifetime_kwh": "Total energi", "online": "Online",
    "pv_power_w": "Solproduktion", "today_kwh": "Producerat idag", "economy_mode": "Economy-läge", "error": "Felkod",
    "in_use": "I bruk", "climate": "Klimatenhet", "water_heater": "Värmare", "room_target": "Rumsbörvärde", "power_phases": "Effekt per fas",
    "inside_temp": "Innetemperatur (bil)", "outside_temp": "Utetemperatur (bil)", "range": "Räckvidd", "enable_switch": "Påslagsbrytare",
    "smart_plug": "Smart kontakt", "mode_select": "Lägesväljare", "circuit_limit": "Kretsgräns", "charging_amps": "Laddström (bilen)",
    "compressor": "Kompressor", "curve_offset": "Kurvförskjutning", "tracker": "Position", "lock": "Lås",
}
_SECTIONS = (("heat_pump", "Värmepump"), ("spa", "Spabad"), ("solar", "Solceller"), ("battery", "Batteri"), ("power_meter", "Elmätare"))
_ENTITY = re.compile(r"^[a-z_]+\.[A-Za-z0-9_\-]+$")


def _is_entity(v) -> bool:
    return isinstance(v, str) and bool(_ENTITY.match(v)) and "." in v


def _walk(obj, path=()):
    """(nyckelväg, entitets-id) för alla entitetssträngar i en dict/lista."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, path)
    elif _is_entity(obj):
        yield path, obj


def label_for(path) -> str:
    key = path[-1] if path else ""
    if len(path) >= 2 and path[-2] in ("safety", "activities"):
        return f"{path[-2] == 'safety' and 'Skydd' or 'Aktivitet'}: {key.replace('_', ' ')}"
    return _LABELS.get(key, key.replace("_", " ").capitalize() if key else "Entitet")


def _kind(path, domain=""):
    key = (path[-1] if path else "").lower()
    if domain in _FLAG_DOMAINS:
        return "other"
    if any(x in key for x in ("lifetime", "today_kwh", "session")):
        return "energy"
    if "soc" in key or key.endswith("level"):
        return "percent"
    if "temp" in key and "target" not in key:
        return "temp"
    if "temp" in key:
        return "temp"
    if any(x in key for x in ("power", "_w", "_kw", "current", "amps", "effekt")):
        return "power"
    return "other"


def _age_min(st, now):
    for field in ("last_reported", "last_updated", "last_changed"):
        raw = (st or {}).get(field)
        if raw:
            try:
                t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return max(0.0, (now - t).total_seconds() / 60.0)
            except ValueError:
                continue
    return None


def _num(v):
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def evaluate(path, entity, states, now):
    """Ett resultat {label, entity, status, note} för en entitet."""
    label = label_for(path)
    row = {"label": label, "entity": entity, "status": OK, "note": ""}
    st = (states or {}).get(entity)
    domain = entity.split(".", 1)[0]
    if st is None:
        row.update(status=FAIL, note="Finns inte i Home Assistant (felstavad, omdöpt eller borttagen?).")
        return row
    raw = str(st.get("state"))
    if raw == "unavailable":
        row.update(status=FAIL, note="Svarar inte (unavailable).")
        return row
    if domain in _NO_STATE_DOMAINS:
        return row                                               # knappar m.m.: att de finns räcker
    kind = _kind(path, domain)
    attrs = st.get("attributes") or {}
    val = _num(raw)
    if domain in ("climate", "water_heater") and kind == "temp":
        val = _num(attrs.get("current_temperature") if "target" not in path[-1] else attrs.get("temperature"))
        if val is None:
            row.update(status=WARN, note="En climate-entitet: temperaturen ska läsas ur dess attribut, men inget värde finns just nu.")
            return row
    elif raw in ("unknown", "") and domain not in _TRACKERS and kind != "other":
        row.update(status=WARN, note="Värdet är okänt just nu (unknown).")
        return row
    if kind in ("temp", "percent", "power", "energy"):
        if val is None and domain not in _TRACKERS:
            row.update(status=FAIL, note=f"Värdet är inte ett tal ('{raw[:20]}'), men ett tal väntas här.")
            return row
        unit = str(attrs.get("unit_of_measurement") or "")
        if val is not None:
            if kind == "temp" and "F" not in unit and not -60 <= val <= 130:
                row.update(status=WARN, note=f"Orimlig temperatur ({val:g}). Fel entitet eller enhet?")
            elif kind == "percent" and not 0 <= val <= 100:
                row.update(status=WARN, note=f"Procentvärdet {val:g} ligger utanför 0 till 100. Fel entitet eller skala?")
            elif kind == "energy" and val < 0:
                row.update(status=WARN, note=f"Negativ energi ({val:g}).")
    key = (path[-1] if path else "").lower()
    still_ok = domain == "number" or "target" in key or (kind == "power" and val is not None and val == 0)    # börvärden, inställningar och 0 W står still med rätta
    if row["status"] == OK and kind in ("temp", "power", "percent") and domain not in _TRACKERS and not still_ok:
        age = _age_min(st, now)
        if age is not None and age > STALE_MIN:
            row.update(status=WARN, note=f"Inte uppdaterad på {age / 60:.0f} h. Har givaren slutat rapportera?")
    return row


def _group_label(section_key, item, idx):
    if section_key == "evs":
        return item.get("name") or str(item.get("id") or f"Bil {idx + 1}")
    return dict(_SECTIONS).get(section_key, section_key)


def context_notes(cfg) -> list:
    """Sammanhangsregler: [(grupp, {label, entity, status, note})] för kända fallgropar."""
    out = []
    for i, ev in enumerate(cfg.get("evs") or []):
        name = ev.get("name") or str(ev.get("id") or f"Bil {i + 1}")
        ch = ev.get("charger") or {}
        ents = ch.get("entities") or {}
        if ch and ents and not (ents.get("power_kw") or ents.get("power")):
            out.append((f"Laddbox, {name}", {"label": "Effektsensor", "entity": "", "status": WARN,
                        "note": "Ingen effektsensor vald för laddboxen. Då räknas laddningen som 0 kWh och 0 kr i kostnadskortet."}))
        if (ev.get("entities") or {}) and not (ev.get("entities") or {}).get("soc"):
            out.append((name, {"label": "Laddnivå", "entity": "", "status": WARN,
                        "note": "Ingen sensor för bilens laddnivå vald. Planen vet då inte hur mycket bilen behöver."}))
    spa = cfg.get("spa") or {}
    if spa.get("enabled") and not (spa.get("entities") or {}).get("current_temp") and str(spa.get("driver")) in ("gecko", "balboa", "switch", "shelly"):
        out.append(("Spabad", {"label": "Vattentemperatur", "entity": "", "status": FAIL, "note": "Ingen temperatursensor vald för spabadet."}))
    bat = cfg.get("battery") or {}
    if bat.get("enabled") and not (bat.get("entities") or {}).get("soc") and str(bat.get("driver") or "generic") == "generic":
        out.append(("Batteri", {"label": "Laddnivå", "entity": "", "status": FAIL, "note": "Ingen sensor för batteriets laddnivå vald."}))
    return out


def check_entities(cfg: dict, states: dict, now: datetime | None = None) -> list:
    """Grupper [{device, items, worst}] för alla valda entiteter i installationen."""
    now = now or datetime.now(timezone.utc)
    groups = []

    def add(label, items):
        if not items:
            return
        rank = {OK: 0, WARN: 1, FAIL: 2}
        groups.append({"device": label, "items": items, "worst": max((i["status"] for i in items), key=lambda s: rank[s])})

    for key, label in _SECTIONS:
        sec = cfg.get(key)
        if isinstance(sec, dict) and (sec.get("enabled") is not False):
            seen, items = set(), []
            for path, ent in _walk(sec):
                if ent in seen:
                    continue
                seen.add(ent)
                items.append(evaluate(path, ent, states, now))
            add(label, items)
    for i, ev in enumerate(cfg.get("evs") or []):
        name = _group_label("evs", ev, i)
        seen, items, citems = set(), [], []
        for path, ent in _walk({k: v for k, v in ev.items() if k != "charger"}):
            if ent not in seen:
                seen.add(ent)
                items.append(evaluate(path, ent, states, now))
        for path, ent in _walk(ev.get("charger") or {}):
            if ent not in seen:
                seen.add(ent)
                citems.append(evaluate(path, ent, states, now))
        add(name, items)
        add(f"Laddbox, {name}", citems)
    for i, ap in enumerate(cfg.get("appliances") or []):
        ent = ap.get("entity") if isinstance(ap, dict) else None
        if _is_entity(ent):
            add(f"Maskin, {ap.get('name') or i + 1}", [evaluate(("entity",), ent, states, now)])
    if _is_entity(cfg.get("weather_entity")):
        add("Väder", [evaluate(("weather_entity",), cfg["weather_entity"], states, now)])
    for label, row in context_notes(cfg):
        for g in groups:
            if g["device"] == label:
                g["items"].append(row)
                g["worst"] = max((g["worst"], row["status"]), key=lambda s: {OK: 0, WARN: 1, FAIL: 2}[s])
                break
        else:
            add(label, [row])
    return groups


def driver_rows(device: str, state: dict | None, keys) -> dict | None:
    """Läsningar via drivrutinen (för det som inte går via HA-entiteter, t.ex. Modbus): {device, items, worst} eller None.
    keys: [(nyckel, etikett)] ur drivrutinens read_state(). None-värden blir varningar, inte fel."""
    if state is None:
        return {"device": device, "items": [{"label": "Läsning", "entity": "", "status": FAIL,
                                              "note": "Drivrutinen kunde inte läsa något alls."}], "worst": FAIL}
    items = []
    for key, label in keys:
        v = state.get(key)
        if v is None:
            items.append({"label": label, "entity": "", "status": WARN, "note": "Ingen läsning (okänt eller ej vald)."})
        else:
            items.append({"label": label, "entity": "", "status": OK, "note": f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)[:30]})
    rank = {OK: 0, WARN: 1, FAIL: 2}
    return {"device": device, "items": items, "worst": max((i["status"] for i in items), key=lambda s: rank[s])}


def summarize(groups) -> str:
    items = [i for g in groups for i in g["items"]]
    if not items:
        return "Inga entiteter att kontrollera."
    n = {s: sum(1 for i in items if i["status"] == s) for s in (OK, WARN, FAIL)}
    return f"{len(items)} läsningar kontrollerade: {n[OK]} fungerar, {n[WARN]} varningar, {n[FAIL]} fel."
