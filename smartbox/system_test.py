"""system_test.py - "Testa ditt system": kontrollerar att allt man valt i installationen fungerar (idé från Energy Pilot).

Del A (system_check.py): läsningar av alla valda entiteter och drivrutiner, utan kommandon.
Del B (här): styrtester per enhet, var och en med uttryckligt val, bekräftelse och återställning:
  batteri (håll, ladda, ladda ur), värmepump (börvärdet ändras 0,5 °C och återställs), spabad (målvärdet ändras 0,5 °C och
  återställs) och laddbox (6 A i högst 90 s om bilen är inkopplad och inte laddar, sedan 0 A igen).
Allt som ändras skrivs först i en återställningslogg (ew_settings system_test_restore_ops) och återställs alltid, även om
EnergyWizard startar om mitt i (recover).

Batteridelen:

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


RESTORE_OPS = "system_test_restore_ops"
HP_STEP_C, SPA_STEP_C, CHARGE_TEST_A = 0.5, 0.5, 6
WAIT_HP_S, WAIT_SPA_S, WAIT_CHARGER_S = 90, 90, 90
_STATUS_STATES = ("done", "failed", "unavailable", "running")


def _row(tid, name):
    return {"id": tid, "intent": tid, "name": name, "ok": None, "note": "", "measured_w": None, "secs": 0}


def config_tests(house_cfg: dict, battery_cfg: dict | None) -> list:
    """Vilka styrtester som finns att välja, ur konfigurationen (webben visar rutorna). Motorn avgör slutligt vid körning.
    [{id, label, eligible, reason}]"""
    out = []
    bat = battery_cfg or {}
    if bat.get("control") not in (None, "av"):
        ok, why = eligibility(bat, set(_ORDER))
        out.append({"id": "battery", "label": "Batteri: håll, ladda och ladda ur (högst 1 kW)", "eligible": ok, "reason": why})
    hp = house_cfg.get("heat_pump") or {}
    if hp.get("enabled"):
        out.append({"id": "heatpump", "label": "Värmepump: ändra rumsbörvärdet 0,5 °C och sätt tillbaka", "eligible": True, "reason": ""})
    sp = house_cfg.get("spa") or {}
    if sp.get("enabled"):
        out.append({"id": "spa", "label": "Spabad: ändra målvärdet 0,5 °C och sätt tillbaka", "eligible": True, "reason": ""})
    for i, ev in enumerate(house_cfg.get("evs") or []):
        ch = ev.get("charger") or {}
        if ch and ch.get("id") is not None:
            name = ev.get("name") or str(ev.get("id") or i + 1)
            out.append({"id": f"charger:{ch['id']}", "label": f"Laddbox ({name}): 6 A i en minut, bara om bilen är inkopplad och inte laddar",
                        "eligible": True, "reason": ""})
    return out


def _near(a, b, tol=0.15):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def _poll(read, pred, wait_s, sleep, clock, poll_s):
    """Läser tills pred(värde) stämmer två gånger i rad eller tiden är slut. Returnerar (lyckades, sista värdet)."""
    t0, run, last = clock(), 0, None
    while clock() - t0 < wait_s:
        sleep(poll_s)
        last = read()
        run = run + 1 if pred(last) else 0
        if run >= CONSEC:
            return True, last
    return False, last


def run_setpoint_test(tid, name, read, send, step, lo, hi, wait_s, record_restore, clear_restore, sleep, clock, poll_s=POLL_S):
    """Gemensam: ändra ett börvärde en liten bit, kontrollera att det återläses, återställ alltid. read()->float|None, send(x)->bool|None."""
    row = _row(tid, name)
    cur = read()
    if cur is None:
        row["note"] = "Hoppades över: börvärdet kan inte läsas, så det går inte att återställa efteråt."
        return row
    new = cur + step if cur + step <= hi else cur - step
    new = max(lo, min(hi, new))
    record_restore(cur)
    t0 = clock()
    try:
        sent = send(new)
        if sent is False:
            row.update(ok=False, note="Kommandot gick inte att skicka.")
        else:
            ok, last = _poll(read, lambda v: _near(v, new), wait_s, sleep, clock, poll_s)
            row.update(ok=ok, measured_w=None, note=(f"Börvärdet ändrades till {new:g} och lästes tillbaka." if ok else
                       f"Börvärdet blev inte {new:g} inom {wait_s} s (lästes som {last if last is not None else 'inget'})."))
    except Exception as e:
        row.update(ok=False, note=f"Kommandot gav fel ({type(e).__name__}).")
    finally:
        try:
            send(cur)
            back, _ = _poll(read, lambda v: _near(v, cur), 60, sleep, clock, poll_s)
            if back:
                clear_restore()
            else:
                row["note"] += f" Obs: kunde inte bekräfta att börvärdet kom tillbaka till {cur:g}. Kontrollera det."
        except Exception:
            row["note"] += f" Obs: återställningen till {cur:g} misslyckades, kontrollera börvärdet."
        row["secs"] = round(clock() - t0)
    return row


def run_charger_test(tid, name, read_state, set_limit, connected, record_restore, clear_restore, sleep, clock, poll_s=POLL_S):
    """Laddbox: bara om bilen är inkopplad och inte laddar. 6 A i högst WAIT_CHARGER_S, sedan 0 A (som motorn gör när inget ska laddas)."""
    row = _row(tid, name)
    st = read_state() or {}
    cur_a = st.get("current_a")
    if not connected(st):
        row["note"] = "Hoppades över: ingen bil är inkopplad."
        return row
    if cur_a is not None and cur_a >= 1.5:
        row["note"] = "Hoppades över: bilen laddar redan, och det vill vi inte störa."
        return row
    record_restore(0)
    t0 = clock()
    try:
        sent = set_limit(CHARGE_TEST_A)
        if sent is False:
            row.update(ok=False, note="Kommandot gick inte att skicka till laddboxen.")
        else:
            best = {"a": None}

            def amps():
                v = (read_state() or {}).get("current_a")
                if v is not None and (best["a"] is None or v > best["a"]):
                    best["a"] = v
                return v
            ok, _ = _poll(amps, lambda v: v is not None and v >= CHARGE_TEST_A - 2, WAIT_CHARGER_S, sleep, clock, poll_s)
            row.update(ok=ok, measured_w=None if best["a"] is None else round(best["a"] * 230),
                       note=(f"Laddboxen släppte fram ström ({best['a']:.0f} A)." if ok else
                             f"Ingen ström kom (mest {best['a'] if best['a'] is not None else 0:g} A). Bilen kan vara fulladdad, sova eller ha laddningen avstängd."))
    except Exception as e:
        row.update(ok=False, note=f"Kommandot gav fel ({type(e).__name__}).")
    finally:
        try:
            set_limit(0)
            clear_restore()
        except Exception:
            row["note"] += " Obs: kunde inte sätta tillbaka laddgränsen till 0 A. Kontrollera laddboxen."
        row["secs"] = round(clock() - t0)
    return row


def collect_reads(ctx, now=None):
    """Del A: entiteter ur konfigurationen och drivrutinernas läsningar. Fel i en drivrutin får aldrig fälla testet."""
    import system_check as sc
    groups = []
    try:
        groups = sc.check_entities(ctx.get("house_cfg") or {}, ctx["states"](), now)
    except Exception as e:
        groups = [{"device": "Kontroll av entiteter", "items": [{"label": "Fel", "entity": "", "status": sc.FAIL,
                   "note": f"Kunde inte läsa installationen ({type(e).__name__})."}], "worst": sc.FAIL}]
    probes = []
    if ctx.get("heatpump") is not None:
        probes.append(("Värmepump, drivrutinens läsning", ctx["heatpump"].read_state, [("indoor_temp", "Innetemperatur"), ("outdoor_temp", "Utetemperatur"),
                       ("forward_temp", "Framledning"), ("return_temp", "Retur"), ("dhw_temp", "Varmvatten")]))
    if ctx.get("spa") is not None:
        probes.append(("Spabad, drivrutinens läsning", ctx["spa"].read_state, [("current_temp", "Vattentemperatur"), ("target_temp", "Målvärde")]))
    for pid, c in (ctx.get("chargers") or {}).items():
        probes.append((f"{c['label']}, drivrutinens läsning", c["driver"].read_state, [("status", "Status"), ("current_a", "Ström"), ("power_kw", "Effekt")]))
    if (ctx.get("battery") or {}).get("driver") is not None:
        probes.append(("Batteri, drivrutinens läsning", ctx["battery"]["driver"].read_state, [("soc_pct", "Laddnivå"), ("power_w", "Effekt")]))
    for label, fn, keys in probes:
        try:
            state = fn()
        except Exception:
            state = None
        g = sc.driver_rows(label, state, keys)
        if g:
            groups.append(g)
    return groups


def summary_all(reads, steps) -> str:
    import system_check as sc
    parts = []
    if reads:
        parts.append("Läsningar: " + sc.summarize(reads))
    tried = [r for r in steps if r["ok"] is not None]
    if tried:
        bad = [r["name"] for r in tried if not r["ok"]]
        parts.append("Styrning: allt som provades fungerade." if not bad else f"Styrning: det här fungerade inte: {', '.join(bad)}.")
    elif steps:
        parts.append("Styrning: inget kunde provas.")
    return " ".join(parts) if parts else "Inget kunde provas."


def _ops(ew_settings) -> list:
    v = ew_settings.get(RESTORE_OPS)
    return list(v) if isinstance(v, list) else []


def start(ctx, selected, set_override, ew_settings, shadow_mod, sleep=time.sleep, clock=time.monotonic):
    """Startar testet (del A, sedan valda styrtester) i en egen tråd. selected: lista med test-id eller None (alla).
    ctx: {house_cfg, states(), battery:{driver,cfg,apply}, heatpump, spa, chargers:{id:{driver,label,connected}}}.
    Returnerar (startade, förklaring)."""
    if _active.is_set():
        return False, "Ett test pågår redan."
    started = datetime.now().isoformat(timespec="seconds")
    _active.set()
    body = {"state": "running", "phase": "reads", "step": None, "started": started, "reads": [], "steps": []}

    def publish(state=None, **kw):
        if state:
            body["state"] = state
        body.update(kw)
        try:
            set_override(OVERRIDE_STATUS, json.dumps(body, ensure_ascii=False))
        except Exception:
            pass

    def add_restore(op_id, value):
        ops = [o for o in _ops(ew_settings) if o.get("id") != op_id] + [{"id": op_id, "value": value}]
        ew_settings.update(**{RESTORE_OPS: ops})

    def drop_restore(op_id):
        ew_settings.update(**{RESTORE_OPS: [o for o in _ops(ew_settings) if o.get("id") != op_id]})

    def job():
        try:
            import homeassistant
            try:
                homeassistant.update_states()
            except Exception:
                pass
            body["reads"] = collect_reads(ctx)
            publish(phase="controls")
            want = set(selected) if selected is not None else None

            def chosen(tid):
                return want is None or tid in want

            def read_fresh(fn):
                def r():
                    try:
                        homeassistant.update_states()
                    except Exception:
                        pass
                    return fn()
                return r

            with shadow_mod.bypass():
                bat = ctx.get("battery")
                if bat and chosen("battery"):
                    drv, cfg = bat["driver"], bat.get("cfg") or {}
                    intents = set(drv.supported_intents())
                    ok, why = eligibility(cfg, intents)
                    if not ok:
                        r = _row("battery", "Batteri"); r["note"] = "Hoppades över: " + why
                        body["steps"].append(r); publish()
                    else:
                        ew_settings.update(**{SETTING_RESTORE: True})
                        stt = drv.read_state() or {}
                        base = len(body["steps"])

                        def pub_b(rows, cur):
                            body["steps"][base:] = [dict(x, id="battery:" + x["intent"], name="Batteri: " + x["name"]) for x in rows]
                            publish(step=cur)
                        rows = run_steps(intents, stt.get("soc_pct"), cfg.get("reserve_soc"), cfg.get("max_power_w"), bat["apply"],
                                         read_fresh(lambda: (lambda w: float(w) if isinstance(w, (int, float)) and w == w else None)(
                                             (drv.read_state() or {}).get("power_w"))), sleep, clock, pub_b)
                        pub_b(rows, None)
                        restored = False
                        try:
                            restored = bool(bat["apply"]("auto", None)) if "auto" in intents else False
                        except Exception:
                            restored = False
                        if restored or "auto" not in intents:
                            ew_settings.update(**{SETTING_RESTORE: False})
                hp = ctx.get("heatpump")
                if hp is not None and chosen("heatpump"):
                    if hasattr(hp, "read_room_target") and hp.read_room_target() is not None:
                        publish(step="heatpump")
                        r = run_setpoint_test("heatpump", "Värmepump: rumsbörvärde", read_fresh(hp.read_room_target),
                                              lambda v: hp.set_room_temp(round(v, 1)), HP_STEP_C, 5.0, 30.0, WAIT_HP_S,
                                              lambda v: add_restore("heatpump", v), lambda: drop_restore("heatpump"), sleep, clock)
                    else:
                        r = _row("heatpump", "Värmepump: rumsbörvärde")
                        r["note"] = ("Hoppades över: värmepumpens börvärde kan inte läsas tillbaka, så EnergyWizard kan inte återställa det "
                                     "efter ett test. Då provas inte styrningen.")
                    body["steps"].append(r); publish()
                sp = ctx.get("spa")
                if sp is not None and chosen("spa"):
                    publish(step="spa")
                    r = run_setpoint_test("spa", "Spabad: målvärde", read_fresh(lambda: (sp.read_state() or {}).get("target_temp")),
                                          lambda v: sp.set_target_temp(round(v, 1)), SPA_STEP_C, 15.0, 40.0, WAIT_SPA_S,
                                          lambda v: add_restore("spa", v), lambda: drop_restore("spa"), sleep, clock)
                    body["steps"].append(r); publish()
                for pid, c in (ctx.get("chargers") or {}).items():
                    tid = f"charger:{pid}"
                    if not chosen(tid):
                        continue
                    publish(step=tid)
                    r = run_charger_test(tid, c["label"] + ": 6 A", read_fresh(c["driver"].read_state),
                                         lambda a, d=c["driver"]: d.set_limit_a(a, reason="systemtest"), c["connected"],
                                         lambda v, t=tid: add_restore(t, v), lambda t=tid: drop_restore(t), sleep, clock)
                    body["steps"].append(r); publish()
            print("🧪 Systemtest klart: " + "; ".join(f"{r['id']}={'ok' if r['ok'] else 'fel' if r['ok'] is False else 'hoppad'}"
                                                     for r in body["steps"]) + "; " + __import__("system_check").summarize(body["reads"]))
            publish("done", step=None, phase="done", summary=summary_all(body["reads"], body["steps"]),
                    finished=datetime.now().isoformat(timespec="seconds"))
        except Exception as e:
            publish("failed", step=None, summary=f"Testet avbröts ({type(e).__name__}).", finished=datetime.now().isoformat(timespec="seconds"))
        finally:
            _active.clear()

    threading.Thread(target=job, name="ew-system-test", daemon=True).start()
    return True, ""


def recover(ctx, ew_settings, shadow_mod) -> bool:
    """Vid uppstart: har ett test avbrutits (omstart mitt i) återställs allt det ändrat. True om något återställdes."""
    done = False
    try:
        with shadow_mod.bypass():
            if ew_settings.get(SETTING_RESTORE):
                bat = ctx.get("battery")
                if bat and "auto" in set(bat["driver"].supported_intents()) and bat["apply"]("auto", None):
                    ew_settings.update(**{SETTING_RESTORE: False})
                    done = True
            left = []
            for op in _ops(ew_settings):
                oid, val, ok = op.get("id"), op.get("value"), False
                try:
                    if oid == "heatpump" and ctx.get("heatpump") is not None:
                        ok = ctx["heatpump"].set_room_temp(float(val)) is not False
                    elif oid == "spa" and ctx.get("spa") is not None:
                        ctx["spa"].set_target_temp(float(val)); ok = True
                    elif str(oid).startswith("charger:"):
                        c = (ctx.get("chargers") or {}).get(str(oid).split(":", 1)[1])
                        if c is not None:
                            ok = c["driver"].set_limit_a(int(val), reason="systemtest") is not False
                except Exception:
                    ok = False
                if ok:
                    done = True
                else:
                    left.append(op)
            if len(left) != len(_ops(ew_settings)):
                ew_settings.update(**{RESTORE_OPS: left})
        if done:
            print("🔧 Avbrutet systemtest: det som ändrats återställdes.")
    except Exception as e:
        print(f"⚠️ Återställning efter systemtest: {e}")
    return done
