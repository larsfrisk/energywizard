"""mqtt_bridge.py - EnergyWizard i Home Assistant via MQTT med autodiscovery (idé från FTW, docs/ha-integration.md).

Utan MQTT publicerar ha_publisher.py sina sensorer via HA:s REST-API: de saknar unikt id, går inte att redigera i HA
och försvinner när HA startar om (tills nästa minut). Med en MQTT-broker inställd (Inställningar -> Home Assistant via
MQTT, eller MQTT_HOST m.fl.) blir samma sensorer riktiga entiteter under enheten "EnergyWizard", och två brytare
går att styra från HA: Skuggläge och Automatisk exportstyrning. Varje bil får dessutom en väljare, Laddläge (Auto,
Ladda nu, Pausa), som EnergyWizards Bil-kort (ha-cards/) visar som knappar (#557).

- Samma entitets-id som förut (sensor.smartbox_* via default_entity_id/object_id), så befintliga dashboards fungerar.
  De gamla REST-entiteterna tas bort en gång innan discovery skickas, annars skulle HA ge de nya ett _2-suffix.
- Tillgänglighet (energywizard/status) med "last will": stannar EnergyWizard visas entiteterna som otillgängliga.
- Status skrivs till inställningarna (mqtt_status) så att webben kan visa om anslutningen fungerar.
- Rör aldrig styrningen: egen tråd, alla fel fångas.
"""
import json
import os
import threading
import time

PREFIX = "homeassistant"
BASE = "energywizard"
AVAIL = f"{BASE}/status"
DEVICE = {"identifiers": ["energywizard"], "name": "EnergyWizard", "manufacturer": "EnergyWizard Open",
          "model": "smartbox", "sw_version": os.environ.get("APP_VERSION", "dev")}
SWITCHES = {                    # nycklar och id i ASCII (HA:s entitets-id), visningsnamnen på svenska
    "shadow_mode": ("energywizard_shadow_mode", "Skuggläge", "mdi:incognito"),
    "auto_export": ("energywizard_auto_export", "Automatisk exportstyrning", "mdi:solar-power"),
}

_state = {"client": None, "cfg": None, "removed_rest": False}


def config() -> dict | None:
    """Broker ur inställningarna (webben) eller miljön. None = MQTT av."""
    try:
        import ew_settings
        st = ew_settings.load()
    except Exception:
        st = {}
    host = (st.get("mqtt_host") or os.environ.get("MQTT_HOST", "")).strip()
    if not host:
        return None
    return {"host": host, "port": int(st.get("mqtt_port") or os.environ.get("MQTT_PORT") or 1883),
            "user": st.get("mqtt_user") or os.environ.get("MQTT_USER") or None,
            "password": st.get("mqtt_password") or os.environ.get("MQTT_PASSWORD") or None}


def active() -> bool:
    c = _state["client"]
    return c is not None and c.is_connected()


def _status(ok: bool, msg: str):
    try:
        import ew_settings
        ew_settings.update(mqtt_status={"ok": ok, "msg": msg, "at": int(time.time())})
    except Exception:
        pass


def _object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


def discovery_payload(entity_id: str, attrs: dict) -> tuple:
    """(topic, payload) för en sensors discovery-konfiguration. Ren funktion - testas i tests/test_mqtt_bridge.py."""
    domain = entity_id.split(".", 1)[0]
    oid = _object_id(entity_id)
    name = str(attrs.get("friendly_name") or oid)
    for p in ("Smartbox ", "smartbox "):
        if name.startswith(p):
            name = name[len(p):]
    cfg = {"name": name, "unique_id": f"energywizard_{oid}", "object_id": oid, "default_entity_id": entity_id,
           "state_topic": f"{BASE}/{oid}/state", "json_attributes_topic": f"{BASE}/{oid}/attributes",
           "availability_topic": AVAIL, "device": DEVICE}
    for k in ("unit_of_measurement", "device_class", "icon", "state_class"):
        if attrs.get(k):
            cfg[k] = attrs[k]
    if domain == "binary_sensor":
        cfg.update(payload_on="on", payload_off="off")
    return f"{PREFIX}/{domain}/{BASE}/{oid}/config", cfg


def switch_payload(key: str) -> tuple:
    oid, name, icon = SWITCHES[key]
    return f"{PREFIX}/switch/{BASE}/{oid}/config", {
        "name": name, "unique_id": oid, "object_id": oid, "default_entity_id": f"switch.{oid}", "icon": icon,
        "state_topic": f"{BASE}/switch/{key}/state", "command_topic": f"{BASE}/switch/{key}/set",
        "payload_on": "ON", "payload_off": "OFF", "availability_topic": AVAIL, "device": DEVICE}


def _switch_state(key: str) -> bool:
    if key == "shadow_mode":
        import shadow
        return shadow.active()
    import logger
    return str(logger.get_all_overrides().get("solar_auto_export", "true")).lower() != "false"


def _set_switch(key: str, on: bool):
    if key == "shadow_mode":
        import ew_settings
        ew_settings.update(shadow_mode=True if on else None)
    else:
        import logger
        logger.set_override("solar_auto_export", "true" if on else "false")
    print(f"📡 MQTT: {SWITCHES[key][1]} {'på' if on else 'av'} (från Home Assistant)")


CAR_MODES = ("Auto", "Ladda nu", "Pausa")
_HOUSE_CFG = os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")


def cars() -> list:
    """[(id, namn, maxström)] ur installationen (evs). Tom lista om installationen inte kan läsas."""
    try:
        import house_config
        out = []
        for ev in (house_config.load_house_config(_HOUSE_CFG).get("evs") or []):
            cid = str(ev.get("id") or "")
            if cid and all(ch.isalnum() or ch == "_" for ch in cid):
                try:
                    amps = int((ev.get("charger") or {}).get("max_a") or 16)
                except (TypeError, ValueError):
                    amps = 16
                out.append((cid, str(ev.get("name") or cid), max(6, min(amps, 32))))
        return out
    except Exception:
        return []


def car_select_payload(cid: str, name: str) -> tuple:
    """(topic, payload) för en bils Laddläge-väljare. Ren funktion."""
    oid = f"energywizard_ev_{cid}_mode"
    return f"{PREFIX}/select/{BASE}/{oid}/config", {
        "name": f"{name}: laddläge", "unique_id": oid, "object_id": oid, "default_entity_id": f"select.{oid}",
        "icon": "mdi:ev-station", "options": list(CAR_MODES), "state_topic": f"{BASE}/select/ev_{cid}/state",
        "command_topic": f"{BASE}/select/ev_{cid}/set", "availability_topic": AVAIL, "device": DEVICE}


def car_mode(cid: str, overrides: dict) -> str:
    """Bilens läge ur överstyrningarna: tvång = Ladda nu, spärr = Pausa, annars Auto (AI-schemat)."""
    forced = str(overrides.get(f"{cid}_force_amps") or "0").strip()
    if forced.isdigit() and int(forced) > 0:
        return "Ladda nu"
    return "Pausa" if str(overrides.get(f"{cid}_hold") or "").lower() == "on" else "Auto"


def apply_car_mode(cid: str, option: str, max_a: int, set_override) -> bool:
    """Samma överstyrningar som appens knappar (ewapp). Ladda nu laddar tills bilen är full eller kabeln dras ur
    (charge_now.py). False om alternativet är okänt."""
    if option == "Ladda nu":
        for k, v in {f"{cid}_hold": "off", f"{cid}_force_amps": str(int(max_a)), f"{cid}_force_phases": "0",
                     f"{cid}_charge_now_target": "", f"{cid}_charge_now_until": ""}.items():
            set_override(k, v)
    elif option == "Pausa":
        for k, v in {f"{cid}_charge_now_target": "", f"{cid}_charge_now_until": "", f"{cid}_force_amps": "0",
                     f"{cid}_force_phases": "0", f"{cid}_hold": "on"}.items():
            set_override(k, v)
    elif option == "Auto":
        for k, v in {f"{cid}_charge_now_target": "", f"{cid}_charge_now_until": "", f"{cid}_hold": "off",
                     f"{cid}_force_amps": "0", f"{cid}_force_phases": "0", "force_ev_recalc": "true"}.items():
            set_override(k, v)
    else:
        return False
    print(f"📡 MQTT: {cid} laddläge {option} (från Home Assistant)")
    return True


def _publish_car_states(client):
    try:
        import logger
        ov = logger.get_all_overrides()
        for cid, _name, _amps in cars():
            client.publish(f"{BASE}/select/ev_{cid}/state", car_mode(cid, ov), retain=True)
    except Exception as e:
        print(f"⚠️ MQTT bilstatus: {e}")


def _connect(cfg):
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="energywizard-smartbox")
    if cfg["user"]:
        c.username_pw_set(cfg["user"], cfg["password"])
    c.will_set(AVAIL, "offline", retain=True)

    def on_connect(client, userdata, flags, reason, props=None):
        if getattr(reason, "is_failure", False):
            _status(False, f"Brokern nekade anslutningen: {reason}")
            return
        client.publish(AVAIL, "online", retain=True)
        for key in SWITCHES:
            topic, payload = switch_payload(key)
            client.publish(topic, json.dumps(payload, ensure_ascii=False), retain=True)
            client.subscribe(f"{BASE}/switch/{key}/set")
        for cid, name, _amps in cars():
            topic, payload = car_select_payload(cid, name)
            client.publish(topic, json.dumps(payload, ensure_ascii=False), retain=True)
            client.subscribe(f"{BASE}/select/ev_{cid}/set")
        _status(True, f"Ansluten till {cfg['host']}:{cfg['port']}")
        print(f"📡 MQTT: ansluten till {cfg['host']}:{cfg['port']} - EnergyWizard syns som enhet i Home Assistant")

    def on_message(client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) == 4 and parts[1] == "select" and parts[2].startswith("ev_"):
                cid = parts[2][3:]
                spec = {c[0]: c for c in cars()}.get(cid)
                if spec:
                    import logger
                    if apply_car_mode(cid, msg.payload.decode().strip(), spec[2], logger.set_override):
                        _publish_car_states(client)
                return
            key = parts[2]
            if key in SWITCHES:
                _set_switch(key, msg.payload.decode().strip().upper() == "ON")
                client.publish(f"{BASE}/switch/{key}/state", "ON" if _switch_state(key) else "OFF", retain=True)
        except Exception as e:
            print(f"⚠️ MQTT-kommando: {e}")

    c.on_connect = on_connect
    c.on_message = on_message
    c.connect_async(cfg["host"], cfg["port"], keepalive=60)
    c.loop_start()
    return c


def ensure():
    """Anropas varje minut av ha_publisher: (åter)ansluter när inställningarna ändrats, kopplar ner när MQTT stängts av."""
    cfg = config()
    if cfg == _state["cfg"] and (_state["client"] is not None or cfg is None):
        return
    old = _state["client"]
    if old is not None:
        try:
            old.publish(AVAIL, "offline", retain=True)
            old.loop_stop()
            old.disconnect()
        except Exception:
            pass
    _state.update(client=None, cfg=cfg, removed_rest=False)
    if cfg is None:
        return
    try:
        _state["client"] = _connect(cfg)
    except Exception as e:
        _status(False, f"Kunde inte ansluta till {cfg['host']}:{cfg['port']}: {e}")
        print(f"⚠️ MQTT: {e}")


def publish(entities: dict) -> bool:
    """Publicerar ha_publisher._collect() via MQTT. False = MQTT inte aktivt (ha_publisher använder REST som förut)."""
    if not active():
        return False
    c = _state["client"]
    if not _state["removed_rest"]:                   # de gamla REST-entiteterna bort, annars får de nya _2-suffix
        try:
            import homeassistant
            for entity_id in entities:
                homeassistant.requests.delete(f"{homeassistant._BASE}/states/{entity_id}", headers=homeassistant._HEADERS,
                                              timeout=3, verify=homeassistant._VERIFY)
        except Exception:
            pass
        _state["removed_rest"] = True
    for entity_id, (state, attrs) in entities.items():
        if state is None:
            continue
        topic, payload = discovery_payload(entity_id, attrs or {})
        c.publish(topic, json.dumps(payload, ensure_ascii=False), retain=True)
        oid = _object_id(entity_id)
        c.publish(f"{BASE}/{oid}/state", str(state), retain=True)
        extra = {k: v for k, v in (attrs or {}).items()
                 if k not in ("friendly_name", "unit_of_measurement", "device_class", "icon", "state_class")}
        c.publish(f"{BASE}/{oid}/attributes", json.dumps(extra, ensure_ascii=False, default=str), retain=True)
    for key in SWITCHES:
        c.publish(f"{BASE}/switch/{key}/state", "ON" if _switch_state(key) else "OFF", retain=True)
    _publish_car_states(c)
    return True
