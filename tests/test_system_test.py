"""Testa ditt system (system_test.py): stegen, hoppa över, avbrott och återställning. Ingen riktig batteridrivrutin, ingen sömn."""
import json

import system_test as st


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


def _run(responses, intents=("hold", "charge", "discharge"), soc=60, reserve=20, apply_ok=True):
    """responses: per intent en lista effekt (W) som read_fn ger i tur och ordning (sista upprepas)."""
    c = Clock(); cur = {"i": None, "n": 0}; log = []

    def apply_fn(intent, power):
        log.append((intent, power)); cur["i"], cur["n"] = intent, 0
        return apply_ok

    def read_fn():
        seq = responses.get(cur["i"]) or [0]
        v = seq[min(cur["n"], len(seq) - 1)]; cur["n"] += 1
        return v

    steps = st.run_steps(intents, soc, reserve, 5000, apply_fn, read_fn, c.sleep, c, lambda s, i: None)
    return steps, log


def test_allt_fungerar():
    steps, log = _run({"hold": [300, 40, 20], "charge": [100, 900, 950], "discharge": [-50, -800, -900]})
    assert [s["ok"] for s in steps] == [True, True, True]
    assert log == [("hold", None), ("charge", 1000.0), ("discharge", 1000.0)]        # aldrig mer än 1 kW
    assert "fungerade" in st.summary(steps)


def test_batteri_som_inte_laddar_blir_ett_fel_med_forklaring():
    steps, _ = _run({"hold": [0, 0], "charge": [10, 20, 30], "discharge": [-900, -900]})
    assert steps[1]["ok"] is False and "inte som beställt" in steps[1]["note"] and steps[1]["measured_w"] == 30
    assert "ladda" in st.summary(steps)
    assert steps[1]["secs"] >= st.STEP_S - st.POLL_S                 # provade hela tiden innan det gav upp


def test_steg_som_inte_gar_att_prova_hoppas_over():
    full, _ = _run({"hold": [0, 0]}, soc=99)
    assert [s["ok"] for s in full] == [True, None, None] or full[1]["ok"] is None
    assert full[1]["ok"] is None and "fullt" in full[1]["note"]
    low, _ = _run({"hold": [0, 0], "charge": [900, 900]}, soc=22, reserve=20)
    assert low[2]["ok"] is None and "reserven" in low[2]["note"]


def test_kommando_som_inte_gar_att_skicka_ger_fel_utan_att_vanta():
    steps, _ = _run({}, intents=("hold",), apply_ok=False)
    assert steps[0]["ok"] is False and "inte att skicka" in steps[0]["note"]


def test_drivrutin_som_kastar_fel_fäller_inte_testet():
    c = Clock()
    def boom(i, p): raise RuntimeError("x")
    steps = st.run_steps(("hold",), 50, 20, 3000, boom, lambda: 0, c.sleep, c, lambda s, i: None)
    assert steps[0]["ok"] is False and "RuntimeError" in steps[0]["note"]


def test_bara_lagen_drivrutinen_har_provas():
    steps, log = _run({"hold": [0, 0]}, intents=("hold", "auto"))
    assert [s["intent"] for s in steps] == ["hold"]


def test_avlasning_saknas_ger_tydligt_besked():
    steps, _ = _run({"hold": [None, None, None]}, intents=("hold",))
    assert steps[0]["ok"] is False and "Ingen effekt" in steps[0]["note"]


def test_tillstand_for_att_fa_prova():
    assert st.eligibility({"control": "styr"}, {"hold", "charge"})[0] is True
    assert "samarbete" in st.eligibility({"control": "samarbete"}, {"hold"})[1]
    assert "styrning" in st.eligibility({"control": "läs"}, {"hold"})[1]
    assert st.eligibility({"control": "av"}, {"hold"})[0] is False
    assert "bara läsning" in st.eligibility({"control": "styr"}, set())[1]


class Sh:
    import contextlib

    @staticmethod
    @contextlib.contextmanager
    def bypass():
        yield


class Settings:
    def __init__(self, **d): self.d = dict(d)
    def update(self, **k): self.d.update(k)
    def get(self, k): return self.d.get(k)


def _wait_done(ov):
    import time
    for _ in range(300):
        if json.loads(ov.get(st.OVERRIDE_STATUS, "{}")).get("state") in ("done", "failed"):
            break
        time.sleep(0.02)
    return json.loads(ov[st.OVERRIDE_STATUS])


class BatDrv:
    def supported_intents(self): return {"hold", "charge", "auto"}
    def read_state(self): return {"soc_pct": 60, "power_w": 0}


def test_start_med_batteri_aterstaller_till_auto_och_skriver_status():
    sent, ov, s = [], {}, Settings()
    c = Clock()
    ctx = {"house_cfg": {}, "states": lambda: {}, "battery": {"driver": BatDrv(), "cfg": {"control": "styr", "reserve_soc": 20, "max_power_w": 4000},
                                                               "apply": lambda i, p: sent.append((i, p)) or True}}
    ok, _ = st.start(ctx, ["battery"], lambda k, v: ov.__setitem__(k, v), s, Sh, sleep=c.sleep, clock=c)
    assert ok is True
    body = _wait_done(ov)
    assert body["state"] == "done" and sent[-1] == ("auto", None)
    assert s.get(st.SETTING_RESTORE) is False and not st.active()
    assert all(r["id"].startswith("battery:") and r["name"].startswith("Batteri: ") for r in body["steps"])


def test_start_utan_valda_styrtester_gor_bara_lasningar():
    ov, s = {}, Settings()
    ctx = {"house_cfg": {"spa": {"enabled": True, "driver": "gecko", "entities": {"current_temp": "sensor.bad"}}},
           "states": lambda: {"sensor.bad": {"state": "38.5", "attributes": {"unit_of_measurement": "°C"}}}}
    st.start(ctx, [], lambda k, v: ov.__setitem__(k, v), s, Sh)
    body = _wait_done(ov)
    assert body["steps"] == [] and body["reads"][0]["device"] == "Spabad" and "läsningar kontrollerade" in body["summary"]


def test_vardetest_andrar_laser_tillbaka_och_aterstaller():
    c = Clock(); val = {"v": 21.0}; sent = []; rec = {}
    row = st.run_setpoint_test("heatpump", "Värmepump", lambda: val["v"], lambda x: (sent.append(x), val.__setitem__("v", x), True)[2],
                               0.5, 5, 30, 90, lambda v: rec.__setitem__("v", v), lambda: rec.pop("v"), c.sleep, c)
    assert row["ok"] is True and sent == [21.5, 21.0] and val["v"] == 21.0 and "v" not in rec        # ändrat, bekräftat, återställt, loggen tömd


def test_vardetest_utan_atrlasning_hoppas_over_och_ror_ingenting():
    c = Clock(); sent = []
    row = st.run_setpoint_test("hp", "VP", lambda: None, lambda x: sent.append(x), 0.5, 5, 30, 90, lambda v: None, lambda: None, c.sleep, c)
    assert row["ok"] is None and "återställa" in row["note"] and sent == []


def test_vardetest_som_inte_tar_ger_fel_men_aterstaller_anda():
    c = Clock(); sent = []; rec = {}
    row = st.run_setpoint_test("spa", "Spa", lambda: 38.5, lambda x: sent.append(x) or True, 0.5, 15, 40, 30, lambda v: rec.__setitem__("v", v), lambda: rec.pop("v", None), c.sleep, c)
    assert row["ok"] is False and "inte 39" in row["note"] and sent == [39.0, 38.5]
    assert rec == {} and "Obs" not in row["note"]          # värdet ändrades aldrig, så återställningen är bekräftad och loggen tömd


def test_aterstallning_som_inte_kan_bekraftas_ligger_kvar_i_loggen():
    c = Clock(); sent = []; rec = {}; val = {"v": 38.5}
    def send(x):
        sent.append(x)
        if len(sent) == 1:
            val["v"] = x                    # första skrivningen tar, återställningen gör det inte (fast värde)
        return True
    row = st.run_setpoint_test("spa", "Spa", lambda: val["v"], send, 0.5, 15, 40, 30, lambda v: rec.__setitem__("v", v), lambda: rec.pop("v", None), c.sleep, c)
    assert row["ok"] is True and sent == [39.0, 38.5]
    assert rec.get("v") == 38.5 and "Obs" in row["note"]     # loggen ligger kvar tills nästa uppstart, och användaren varnas


def test_vardetest_klipper_at_taket():
    c = Clock(); sent = []
    st.run_setpoint_test("spa", "Spa", lambda: 40.0, lambda x: sent.append(x) or True, 0.5, 15, 40, 20, lambda v: None, lambda: None, c.sleep, c)
    assert sent[0] == 39.5                  # inte över 40


def test_laddbox_provas_bara_nar_bilen_ar_inkopplad_och_inte_laddar():
    c = Clock()
    for stt, why in (({"status": "disconnected", "current_a": 0}, "ingen bil"), ({"status": "charging", "current_a": 10}, "laddar redan")):
        sent = []
        row = st.run_charger_test("c", "Laddbox", lambda s=stt: s, lambda a: sent.append(a) or True, lambda s: s["status"] != "disconnected",
                                  lambda v: None, lambda: None, c.sleep, c)
        assert row["ok"] is None and why in row["note"] and sent == []


def test_laddbox_ger_ström_och_sätts_tillbaka_till_noll():
    c = Clock(); cur = {"a": 0.0}; sent = []; rec = {}
    def set_limit(a): sent.append(a); cur["a"] = 8.0 if a else 0.0; return True
    row = st.run_charger_test("c", "Laddbox", lambda: {"status": "connected_requesting", "current_a": cur["a"]}, set_limit,
                              lambda s: True, lambda v: rec.__setitem__("v", v), lambda: rec.pop("v"), c.sleep, c)
    assert row["ok"] is True and sent == [8, 0] and "v" not in rec and row["measured_w"] == round(8 * 230)


def test_laddbox_som_inte_slapper_fram_strom_ger_fel_och_nollas():
    c = Clock(); sent = []
    row = st.run_charger_test("c", "Laddbox", lambda: {"status": "connected_finished", "current_a": 0.0}, lambda a: sent.append(a) or True,
                              lambda s: True, lambda v: None, lambda: None, c.sleep, c)
    assert row["ok"] is False and "Ingen ström" in row["note"] and sent == [8, 0]
    assert "connected_finished" in row["note"] and str(st.WAIT_CHARGER_S) in row["note"]       # status och väntetid syns i förklaringen


def test_aterstallning_efter_avbrutet_test_gar_igenom_alla_poster():
    class HP:
        def __init__(self): self.set = []
        def set_room_temp(self, v): self.set.append(v); return True
    class Spa:
        def __init__(self): self.set = []
        def set_target_temp(self, v): self.set.append(v)
    class Ch:
        def __init__(self): self.set = []
        def set_limit_a(self, a, reason=None): self.set.append(a); return True
    class Bat:
        def supported_intents(self): return {"auto"}
    hp, spa, ch, sent = HP(), Spa(), Ch(), []
    s = Settings(**{st.SETTING_RESTORE: True, st.RESTORE_OPS: [{"id": "heatpump", "value": 21.0}, {"id": "spa", "value": 38.5},
                                                              {"id": "charger:EH1", "value": 0}, {"id": "heatpump_okänd", "value": 1}]})
    ctx = {"battery": {"driver": Bat(), "apply": lambda i, p: sent.append(i) or True}, "heatpump": hp, "spa": spa, "chargers": {"EH1": {"driver": ch}}}
    assert st.recover(ctx, s, Sh) is True
    assert sent == ["auto"] and hp.set == [21.0] and spa.set == [38.5] and ch.set == [0]
    assert s.get(st.SETTING_RESTORE) is False
    assert s.get(st.RESTORE_OPS) == [{"id": "heatpump_okänd", "value": 1}]            # det som inte kunde återställas ligger kvar
    assert st.recover(ctx, Settings(), Sh) is False                                    # inget kvar att återställa


def test_config_tests_visar_vad_som_gar_att_prova():
    cfg = {"heat_pump": {"enabled": True}, "spa": {"enabled": True},
           "evs": [{"id": "tesla", "name": "Tesla", "charger": {"id": "EH1"}}, {"id": "leaf", "name": "Leaf"}]}
    ids = {t["id"]: t for t in st.config_tests(cfg, {"control": "styr"})}
    assert set(ids) == {"battery", "heatpump", "spa", "charger:EH1"} and all(t["eligible"] for t in ids.values())
    ids = {t["id"]: t for t in st.config_tests(cfg, {"control": "samarbete"})}
    assert ids["battery"]["eligible"] is False and "samarbete" in ids["battery"]["reason"]
    assert "battery" not in {t["id"] for t in st.config_tests(cfg, {"control": "av"})}


def test_lasningar_via_drivrutiner_i_ctx():
    class D:
        def read_state(self): return {"indoor_temp": 21.0, "outdoor_temp": None}
    ctx = {"house_cfg": {}, "states": lambda: {}, "heatpump": D()}
    g = st.collect_reads(ctx)
    assert g[-1]["device"].startswith("Värmepump") and g[-1]["worst"] == "warn"


def test_recover_gar_inte_sonder_utan_nagot_att_aterstalla():
    assert st.recover({}, Settings(), Sh) is False


def test_shadow_bypass_ar_trådlokal():
    import threading
    import shadow
    seen = {}
    with shadow.bypass():
        seen["inne"] = shadow.active()
        t = threading.Thread(target=lambda: seen.__setitem__("annan_trad", shadow.active()))
        t.start(); t.join()
    assert seen["inne"] is False
    assert shadow.active() == seen["annan_trad"]                  # andra trådar påverkas inte


def test_thermia_borvarde_gar_att_lasa_tillbaka():
    from unittest.mock import patch
    from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
    drv = ThermiaHusdataHeatPumpDriver()
    with patch("drivers.heatpump_thermia.pump.read_room_setpoint", return_value=15.5):
        assert drv.read_room_target() == 15.5
    with patch("drivers.heatpump_thermia.pump.read_room_setpoint", return_value=None):
        assert drv.read_room_target() is None


def test_pump_las_enda_registret_for_borvardet():
    from unittest.mock import patch
    import pump
    with patch.object(pump, "PUMP_IPS", ["1.2.3.4"]), patch.object(pump, "_read_holding", return_value=[155]) as rh, \
            patch("shadow.active", return_value=False):
        assert pump.read_room_setpoint() == 15.5
        rh.assert_called_once_with(15, count=1)                     # ett register, inte hela kartan
    with patch.object(pump, "PUMP_IPS", ["1.2.3.4"]), patch.object(pump, "_read_holding", return_value=None), \
            patch("shadow.active", return_value=False), patch("pump.time.sleep"):
        assert pump.read_room_setpoint() is None


def test_motorn_skriver_inte_till_styrda_enheter_under_testet():
    """Källkontroll: de tre skrivvägarna (värmepump, spabad, laddbox) frågar system_test.active() (annars skriver motorn över testet)."""
    import re
    src = open("smartbox/main.py", encoding="utf-8").read()
    assert re.search(r"if needs_update and not system_test\.active\(\)", src)
    assert re.search(r"if HAS_SPA and not system_test\.active\(\) and \(last_sent_spa_target", src)
    assert re.search(r"def charger_set_limit\(cid, amps, reason=None\):\n    if system_test\.active\(\):", src)


def test_drivrutinen_anger_sitt_eget_steg_for_borvardet():
    from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
    from drivers.heatpump_generic import GenericClimateHeatPumpDriver
    assert ThermiaHusdataHeatPumpDriver.room_target_step == 1.0          # sparar bara hela grader
    assert GenericClimateHeatPumpDriver.room_target_step == 0.5
    c = Clock(); val = {"v": 15.0}
    def send(x): val["v"] = float(int(x)); return True              # som Thermia: 15,5 blir 15
    row = st.run_setpoint_test("hp", "VP", lambda: val["v"], send, 0.5, 5, 30, 90, lambda v: None, lambda: None, c.sleep, c)
    assert row["ok"] is False                                         # 0,5-steget syns aldrig: testet visar felet i stället för att gissa
    c = Clock(); val["v"] = 15.0
    row = st.run_setpoint_test("hp", "VP", lambda: val["v"], send, 1.0, 5, 30, 90, lambda v: None, lambda: None, c.sleep, c)
    assert row["ok"] is True and val["v"] == 15.0                     # 1-steget syns och återställs


def test_laddbox_som_vantar_pa_start_far_ett_pa_kommando():
    c = Clock(); cur = {"a": 0.0, "status": "awaiting_start"}; sent = []; started = []
    def set_limit(a): sent.append(a); return True
    def turn_on(): started.append(1); cur["a"] = 8.0; cur["status"] = "charging"
    row = st.run_charger_test("c", "Laddbox", lambda: {"status": cur["status"], "current_a": cur["a"]}, set_limit, lambda s: True,
                              lambda v: None, lambda: None, c.sleep, c, turn_on=turn_on)
    assert row["ok"] is True and started == [1] and sent == [8, 0]          # utan på-kommandot hade boxen aldrig börjat ladda


def test_laddbox_som_redan_ar_pa_far_inget_extra_pa_kommando():
    c = Clock(); cur = {"a": 0.0}; started = []
    def set_limit(a): cur["a"] = 8.0 if a else 0.0; return True
    row = st.run_charger_test("c", "Laddbox", lambda: {"status": "connected_requesting", "current_a": cur["a"]}, set_limit, lambda s: True,
                              lambda v: None, lambda: None, c.sleep, c, turn_on=lambda: started.append(1))
    assert row["ok"] is True and started == []


def test_varmvatten_hittas_aven_nar_drivrutinen_kallar_det_water_temp_top():
    class HP:
        def read_state(self): return {"indoor_temp": 21.0, "outdoor_temp": -2.0, "forward_temp": 41.0, "return_temp": 32.0, "dhw_temp": None}
        def read_sensors(self): return {"water_temp_top": 60.0}
    g = st.collect_reads({"house_cfg": {}, "states": lambda: {}, "heatpump": HP()})
    assert g[-1]["worst"] == "ok" and any(i["label"] == "Varmvatten" and i["status"] == "ok" for i in g[-1]["items"])


def test_laddboxen_far_tid_att_svara_via_molnet():
    c = Clock(); cur = {"a": 0.0}
    def set_limit(a): return True
    def read():
        if c.t >= 150:                       # strömmen syns först efter två och en halv minut (Easee via molnet)
            cur["a"] = 8.0
        return {"status": "charging" if cur["a"] else "awaiting_start", "current_a": cur["a"]}
    row = st.run_charger_test("c", "Laddbox", read, set_limit, lambda s: True, lambda v: None, lambda: None, c.sleep, c)
    assert row["ok"] is True and st.WAIT_CHARGER_S >= 240
