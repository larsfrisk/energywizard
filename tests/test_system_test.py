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


def test_start_aterstaller_alltid_till_auto_och_skriver_status():
    class Drv:
        def supported_intents(self): return {"hold", "charge", "auto"}
        def read_state(self): return {"soc_pct": 60, "power_w": 0}
    class S:
        def __init__(self): self.d = {}
        def update(self, **k): self.d.update(k)
        def get(self, k): return self.d.get(k)
    import contextlib, time
    class Sh:
        @staticmethod
        @contextlib.contextmanager
        def bypass(): yield
    sent, ov, s = [], {}, S()
    c = Clock()
    ok, _ = st.start(Drv(), {"control": "styr", "reserve_soc": 20, "max_power_w": 4000},
                     lambda i, p: sent.append((i, p)) or True, lambda k, v: ov.__setitem__(k, v), s, Sh,
                     sleep=c.sleep, clock=c)
    assert ok is True
    for _ in range(200):
        if json.loads(ov.get(st.OVERRIDE_STATUS, "{}")).get("state") == "done": break
        time.sleep(0.02)
    body = json.loads(ov[st.OVERRIDE_STATUS])
    assert body["state"] == "done" and body["restored"] is True and sent[-1] == ("auto", None)
    assert s.get(st.SETTING_RESTORE) is False and not st.active()


def test_recover_efter_avbrutet_test():
    class Drv:
        def supported_intents(self): return {"hold", "auto"}
    class S:
        d = {st.SETTING_RESTORE: True}
        def update(self, **k): self.d.update(k)
        def get(self, k): return self.d.get(k)
    import contextlib
    class Sh:
        @staticmethod
        @contextlib.contextmanager
        def bypass(): yield
    sent = []; s = S()
    assert st.recover(Drv(), lambda i, p: sent.append(i) or True, s, Sh) is True
    assert sent == ["auto"] and s.get(st.SETTING_RESTORE) is False
    assert st.recover(Drv(), lambda i, p: sent.append(i) or True, s, Sh) is False        # inget kvar att återställa


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
