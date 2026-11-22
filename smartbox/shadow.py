"""Skuggläge: EnergyWizard räknar, planerar och visar allt som vanligt men skickar ingenting till prylarna.

Tanken (önskad av en betatestare 2026-11-03): köra EnergyWizard *bredvid* det system man redan har och se vad det
hade gjort, utan risk. Slås på i webben (Inställningar -> Skuggläge) eller med SHADOW_MODE=true.

Alla skrivvägar frågar active() och loggar i stället med record():
  - homeassistant.py: varje anrop till /api/services/... (klimat, brytare, val, nummer, knappar, Easee, Tesla ...)
  - pump.py (Thermia via Husdata-Modbus), drivrutinerna HeishaMon, NIBE lokalt och myUplink
Läsning och EnergyWizards egna sensorer i HA (sensor.smartbox_*) fungerar som vanligt.

Loggen ligger i tabellen shadow_actions (senaste 7 dygnen) och visas i webben. Samma åtgärd skrivs högst en gång
var tionde minut, så att en regel som körs varje minut inte fyller loggen.
"""
import os
import threading
import time

_last: dict = {}           # (vad) -> senast loggad, för att inte logga samma sak varje minut
REPEAT_S = 600


def scoped_controls(house):
    """Code-owned names only; configured exceptions, not proof of delivery."""
    hp = house.get('heat_pump') or {}
    hw = hp.get('hot_water_control') or {}
    bat = house.get('battery') or {}
    result = []
    if (hp.get('enabled') is True and hw.get('enabled') is True and hw.get('driver') == 'nibe_local'
            and hw.get('temperature_role_verified') is True
            and hw.get('exclusive_owner_confirmed') is True and hw.get('live_control_confirmed') is True):
        result.append('hot_water')
    transport = bat.get('command_transport', 'modbus')
    battery_verified = ((transport == 'modbus' and bat.get('default_mode_verified') is True)
                        or (transport == 'mqtt' and bat.get('mqtt_control_verified') is True))
    if (bat.get('enabled') is True and bat.get('driver') == 'ferroamp_modbus'
            and bat.get('control') == 'styr' and battery_verified
            and bat.get('exclusive_owner_confirmed') is True and bat.get('live_control_confirmed') is True):
        result.append('battery')
    return result


_tl = threading.local()


class bypass:
    """Tillåter skrivningar i den här tråden trots skuggläge (systemtestet, när användaren uttryckligen tryckt på knappen).
    Trådlokal: motorns övriga styrning i andra trådar förblir i skuggläge."""
    def __enter__(self):
        self._prev = getattr(_tl, "bypass", False)
        _tl.bypass = True
        return self

    def __exit__(self, *exc):
        _tl.bypass = self._prev
        return False


def active() -> bool:
    if getattr(_tl, "bypass", False):
        return False
    if os.environ.get("SHADOW_MODE", "").strip().lower() in ("1", "true", "ja", "yes"):
        return True
    try:
        import ew_settings
        return bool(ew_settings.get("shadow_mode", False))
    except Exception:
        return False


def record(what: str, detail: str = "") -> None:
    """Loggar en åtgärd som skulle ha skickats. Får aldrig störa motorn."""
    now = time.time()
    key = f"{what}|{detail}"
    if now - _last.get(key, 0) < REPEAT_S:
        return
    _last[key] = now
    print(f"🕶️ Skuggläge: skulle ha gjort {what} {detail}".rstrip())
    try:
        from logger import get_db
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS shadow_actions (id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), "
                        "what TEXT, detail TEXT)")
            cur.execute("INSERT INTO shadow_actions (what, detail) VALUES (%s, %s)", (what[:200], detail[:500]))
            cur.execute("DELETE FROM shadow_actions WHERE ts < now() - interval '7 days'")
            conn.commit()
    except Exception as e:
        print(f"⚠️ Skuggläget kunde inte logga: {e}")


class FakeResponse:
    """Svar till kod som kontrollerar status_code/raise_for_status/json efter ett (uteblivet) anrop."""
    status_code = 200
    ok = True
    text = "[]"

    def raise_for_status(self):
        return None

    def json(self):
        return []
