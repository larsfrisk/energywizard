"""gpm:s beslut får inte ändras av generaliseringen till N bilar (2026-11-04). Facit genererades med koden
före ombyggnaden (tests/gpm_golden_gen.py): 260 scenarier x 10 varv med Emils två bilar."""
import gzip, json, os
import pytest

import gpm_golden_gen as gen

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "gpm_golden.json.gz")


def _avsiktligt_andrad(states, e_seq):
    """#174 (2026-11-06, avsiktlig ändring): en bil som INTE är inkopplad tvångsladdas inte (Prio 11.5) och hålls inte
    vid liv av kontaktorskyddet (Prio 3.5). Facit gjordes före den ändringen - scenarier där en ej inkopplad bil hade
    tvång eller laddström i facit jämförs inte. Allt annat måste stämma exakt som förut."""
    for car in ("nissan", "tesla"):
        for st, e in zip(states, e_seq):
            if not st.get(f"{car}_connected", True) and (st.get(f"{car}_force_amps", 0) > 0 or (e.get(f"{car}_limit_a") or 0) >= 6):
                return True
    return False


def _morgongolv(states):
    """#302: två inkopplade bilar under 50 % före kl 06 delar säkringen eller turas om.
    Facit gjordes före den ändringen, så de scenariona jämförs inte."""
    for st in states:
        now = st.get("now")
        if now is None or now.hour >= 6:
            continue
        needy = 0
        for car in ("nissan", "tesla"):
            if not st.get(f"{car}_connected", False):
                continue
            soc = st.get(f"{car}_soc")
            if soc is None or soc >= 50:
                continue
            if st.get(f"{car}_hold") or st.get(f"{car}_charge_completed"):
                continue
            if (st.get(f"{car}_force_amps") or 0) > 0:
                continue
            needy += 1
        if needy >= 2:
            return True
    return False


def _okänt_fasläge_först(states, k, diff):
    """1.2.101 (2026-11-15, avsiktlig ändring): okänt fasläge räknas som 3 faser för en bil som kan växla, så
    solladdningen växlar uttryckligen till 1 fas. Scenariot jämförs inte vidare om första avvikelsen är just ett sådant
    fasbyte i ett varv där fasläget var okänt (resten av scenariot följer av det)."""
    st = states[k] if k < len(states) else {}
    return "tesla_set_phases" in diff and diff["tesla_set_phases"][1] is None and not st.get("tesla_phases")


def test_samma_beslut_som_fore_ombyggnaden(monkeypatch):
    # Facit skrevs med låstider i UTC. Testet gäller besluten, så visningstiden låses till UTC (1.2.100 visar husets tid).
    import zoneinfo
    import nordpool
    monkeypatch.setattr(nordpool, "price_timezone", lambda: zoneinfo.ZoneInfo("UTC"))
    expected = json.load(gzip.open(FIX, "rt", encoding="utf-8"))
    got = gen.run()
    assert len(got) == len(expected)
    states = gen.scenarios()
    compared = 0
    for i, (g_seq, e_seq) in enumerate(zip(got, expected)):
        if _avsiktligt_andrad(states[i], e_seq) or _morgongolv(states[i]):
            continue
        compared += 1
        for k, (g, e) in enumerate(zip(g_seq, e_seq)):
            g = {kk: vv for kk, vv in g.items() if kk in e}         # nya nycklar får finnas, gamla måste stämma
            if g != e:
                diff = {kk: (g.get(kk), e.get(kk)) for kk in set(g) | set(e) if g.get(kk) != e.get(kk)}
                if _okänt_fasläge_först(states[i], k, diff):
                    compared -= 1
                    break
                pytest.fail(f"scenario {i} varv {k}: {json.dumps(diff, ensure_ascii=False)[:1500]}")
    # 105 före 1.2.101; okänt fasläge tar bort 39 (jämförs fram till fasbytet), 66 kvar som jämförs helt
    assert compared >= 60, f"för få jämförda scenarier: {compared}"
