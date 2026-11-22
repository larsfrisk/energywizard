"""system_test.py - "Testa ditt system": kontrollerar att batteriet faktiskt gör det EnergyWizard ber om (idé från Energy Pilot).

Bakgrund: många batteriförinställningar är byggda ur integrationens egen kod men aldrig provade på riktig hårdvara. Testet ger
användaren (och oss) ett svar på tio minuter, och erbjuds som sista steg efter installationsguiden.

Gången (högst STEP_S sekunder per steg, avbryts så fort steget lyckats):
  1. håll    - batteriet ska stå still (|effekt| <= HOLD_MAX_W)
  2. ladda   - batteriet ska ladda (>= MOVE_MIN_W), med högst MAX_W
  3. ladda ur - batteriet ska ladda ur (<= -MOVE_MIN_W), med högst MAX_W
  4. tillbaka till auto, alltid, även om något steg misslyckades. Ett ev. omstartat tillstånd (restore-flagga i ew_settings)
     återställs vid nästa uppstart (recover).
Steg som inte går att prova hoppas över med förklaring (batteriet fullt för laddning, nära reserven för urladdning, lägen som
drivrutinen saknar). Motorns egen batteristyrning pausas medan testet pågår (active()), och testets tråd får skicka
riktiga kommandon även i skuggläge (shadow.bypass), eftersom användaren uttryckligen tryckt på knappen.

Webben begär testet via överstyrningen system_test_request och läser förloppet ur system_test_status (JSON). Ren logik
med injicerade funktioner - testas i tests/test_system_test.py.
"""
import json
import threading
import time
from datetime import datetime

OVERRIDE_REQ = "system_test_request"
OVERRIDE_STATUS = "system_test_status"
SETTING_RESTORE = "system_test_restore"
POLL_S = 10
STEP_S = 120
MAX_W = 1000
MOVE_MIN_W = 200
HOLD_MAX_W = 150
CONSEC = 2                    # så många avläsningar i rad måste stämma
CHARGE_MAX_SOC = 97
DISCHARGE_MIN_MARGIN = 5      # urladdning provas bara om laddnivån är minst reserven + så här mycket
_NAMES = {"hold": "Håll", "charge": "Ladda", "discharge": "Ladda ur"}
_ORDER = ("hold", "charge", "discharge")
_active = threading.Event()


def active() -> bool:
    return _active.is_set()


def eligibility(cfg: dict | None, intents) -> tuple:
    """(går det att prova, förklaring). cfg = house_config.battery_settings(...); intents = drivrutinens stödda avsikter."""
    cfg = cfg or {}
    control = str(cfg.get("control") or "av")
    if control == "av":
        return False, "Inget batteri är valt i installationen."
    if control == "samarbete":
        return False, "Batteriet styrs av ett annat system (samarbete). EnergyWizard skickar inga kommandon dit, så det finns inget att prova."
    if control != "styr":
        return False, "Slå på styrning av batteriet först (du kan göra det i skuggläge). Testet skickar riktiga kommandon och kräver att styrning är vald."
    usable = [i for i in _ORDER if i in set(intents or ())]
    if not usable:
        return False, "Batteriets drivrutin har inga lägen att prova (bara läsning)."
    return True, ""


def satisfied(intent: str, watts) -> bool:
    if watts is None:
        return False
    if intent == "hold":
        return abs(watts) <= HOLD_MAX_W
    if intent == "charge":
        return watts >= MOVE_MIN_W
    if intent == "discharge":
        return watts <= -MOVE_MIN_W
    return False


def skip_reason(intent: str, soc, reserve_soc) -> str | None:
    if intent == "charge" and soc is not None and soc >= CHARGE_MAX_SOC:
        return f"Hoppades över: batteriet är fullt ({soc:.0f} %), så det kan inte ladda."
    if intent == "discharge" and soc is not None and reserve_soc is not None and soc < float(reserve_soc) + DISCHARGE_MIN_MARGIN:
        return f"Hoppades över: batteriet ligger nära reserven ({soc:.0f} %), så urladdning provas inte."
    return None


def run_steps(intents, soc, reserve_soc, max_w, apply_fn, read_fn, sleep, clock, publish, poll_s=POLL_S, step_s=STEP_S):
    """Kör stegen och returnerar listan med resultat. apply_fn(intent, power_w)->bool, read_fn()->(effekt W, + = laddar) eller None."""
    steps = []
    power = float(min(max_w or MAX_W, MAX_W))
    for intent in _ORDER:
        if intent not in set(intents):
            continue
        row = {"intent": intent, "name": _NAMES[intent], "ok": None, "note": "", "measured_w": None, "secs": 0}
        steps.append(row)
        why = skip_reason(intent, soc, reserve_soc)
        if why:
            row.update(note=why)
            publish(steps, intent)
            continue
        publish(steps, intent)
        t0 = clock()
        try:
            sent = apply_fn(intent, power if intent in ("charge", "discharge") else None)
        except Exception as e:                                    # en drivrutin får aldrig fälla testet
            sent, row["note"] = False, f"Kommandot gav fel ({type(e).__name__})."
        if not sent:
            row.update(ok=False, note=row["note"] or "Kommandot gick inte att skicka till batteriet.")
            publish(steps, intent)
            continue
        run, best = 0, None
        while clock() - t0 < step_s:
            sleep(poll_s)
            w = read_fn()
            if w is not None and (best is None or (abs(w) > abs(best) if intent != "hold" else abs(w) < abs(best))):
                best = w
            run = run + 1 if satisfied(intent, w) else 0
            if run >= CONSEC:
                break
        ok = run >= CONSEC
        row.update(ok=ok, measured_w=None if best is None else round(best), secs=round(clock() - t0))
        if ok:
            row["note"] = {"hold": "Batteriet stod still.", "charge": "Batteriet laddade.", "discharge": "Batteriet laddade ur."}[intent]
        elif best is None:
            row["note"] = "Ingen effekt kunde läsas från batteriet under steget."
        else:
            row["note"] = {"hold": f"Batteriet rörde sig ({best:.0f} W) trots håll.",
                           "charge": f"Batteriet laddade inte som beställt (mest {best:.0f} W).",
                           "discharge": f"Batteriet laddade inte ur som beställt (mest {best:.0f} W)."}[intent]
        publish(steps, intent)
    return steps


def summary(steps) -> str:
    tried = [s for s in steps if s["ok"] is not None]
    if not tried:
        return "Inget kunde provas."
    bad = [s["name"].lower() for s in tried if not s["ok"]]
    if not bad:
        return "Allt som kunde provas fungerade: batteriet gör som EnergyWizard ber om."
    return f"Det här fungerade inte: {', '.join(bad)}. Skicka resultatet till oss så tittar vi på din förinställning."


def _publish_factory(set_override, started):
    def publish(steps, current, state="running", extra=None):
        body = {"state": state, "step": current, "started": started, "steps": steps}
        body.update(extra or {})
        try:
            set_override(OVERRIDE_STATUS, json.dumps(body, ensure_ascii=False))
        except Exception:
            pass
    return publish


def start(driver, cfg, apply_fn, set_override, ew_settings, shadow_mod, state_reader=None, sleep=time.sleep, clock=time.monotonic):
    """Startar testet i en egen tråd. Returnerar (startade, förklaring)."""
    if _active.is_set():
        return False, "Ett test pågår redan."
    ok, why = eligibility(cfg, driver.supported_intents() if hasattr(driver, "supported_intents") else ())
    if not ok:
        set_override(OVERRIDE_STATUS, json.dumps({"state": "unavailable", "reason": why}, ensure_ascii=False))
        return False, why
    _active.set()
    started = datetime.now().isoformat(timespec="seconds")
    publish = _publish_factory(set_override, started)

    def read():
        try:
            import homeassistant
            homeassistant.update_states()
        except Exception:
            pass
        st = (state_reader or driver.read_state)() or {}
        w = st.get("power_w")
        return float(w) if isinstance(w, (int, float)) and w == w else None

    def job():
        steps = []
        try:
            ew_settings.update(**{SETTING_RESTORE: True})
            st = (state_reader or driver.read_state)() or {}
            with shadow_mod.bypass():
                steps = run_steps(set(driver.supported_intents()), st.get("soc_pct"), (cfg or {}).get("reserve_soc"),
                                  (cfg or {}).get("max_power_w"), apply_fn, read, sleep, clock,
                                  lambda s, cur: publish(s, cur))
                restored = False
                try:
                    restored = bool(apply_fn("auto", None)) if "auto" in set(driver.supported_intents()) else False
                except Exception:
                    restored = False
            if restored or "auto" not in set(driver.supported_intents()):
                ew_settings.update(**{SETTING_RESTORE: False})
            print("🧪 Systemtest klart: " + "; ".join(f"{r['intent']}={'ok' if r['ok'] else 'fel' if r['ok'] is False else 'hoppad'}"
                                                 + (f" ({r['measured_w']} W)" if r.get("measured_w") is not None else "") for r in steps)
                  + f"; återställt={'ja' if restored else 'nej'}")      # följer med i supportunderlaget (support/send)
            publish(steps, None, "done", {"summary": summary(steps), "restored": restored, "finished": datetime.now().isoformat(timespec="seconds")})
        except Exception as e:
            publish(steps, None, "failed", {"summary": f"Testet avbröts ({type(e).__name__}).", "finished": datetime.now().isoformat(timespec="seconds")})
        finally:
            _active.clear()

    threading.Thread(target=job, name="ew-system-test", daemon=True).start()
    return True, ""


def recover(driver, apply_fn, ew_settings, shadow_mod) -> bool:
    """Vid uppstart: har ett test avbrutits (omstart mitt i) lämnar vi inte batteriet i ett provläge. True om något återställdes."""
    try:
        if not ew_settings.get(SETTING_RESTORE):
            return False
        ok = False
        if "auto" in set(driver.supported_intents()):
            with shadow_mod.bypass():
                ok = bool(apply_fn("auto", None))
        if ok:
            ew_settings.update(**{SETTING_RESTORE: False})
        print(f"🔋 Avbrutet systemtest: batteriet {'återställdes till auto' if ok else 'kunde inte återställas, försöker vid nästa start'}.")
        return ok
    except Exception as e:
        print(f"⚠️ Återställning efter systemtest: {e}")
        return False
