"""#141 effektledd: gränsen för timmen håller månadens snitt av de N högsta timmarna i samma trappsteg."""
import capacity_tariff as ct


def test_tre_hogsta_pa_olika_dygn():
    peaks = [(1, 6.0), (1, 7.5), (2, 4.0), (3, 8.0), (4, 3.0)]
    top = ct.top_hours(peaks, 3, True)
    assert top == [(3, 8.0), (1, 7.5), (2, 4.0)]                     # dygn 1 räknas en gång (7,5)


def test_granssnittet_stannar_i_steget():
    # topp: 8, 7.5, 4 -> snitt 6.5 kW, steg 5-10. Ny timme idag (dygn 9) får vara upp till 10*3 - (8+7.5) = 14.5 kW
    peaks = [(1, 7.5), (2, 4.0), (3, 8.0)]
    lim, info = ct.limit_kw(peaks, today=9, top_n=3)
    assert info["step"] == [5.0, 10.0] and abs(lim - 14.5) < 1e-9


def test_timme_under_lagsta_toppen_ar_alltid_fri():
    # snittet redan nära steget: utrymmet blir mindre än den lägsta toppen -> gränsen är den lägsta toppen (påverkar inte)
    peaks = [(1, 9.9), (2, 9.9), (3, 9.0)]
    lim, info = ct.limit_kw(peaks, today=9, top_n=3)
    assert abs(lim - 10.2) < 1e-9 and info["free_below_kw"] == 9.0
    peaks = [(1, 9.9), (2, 9.9), (3, 9.9)]
    lim, _ = ct.limit_kw(peaks, today=9, top_n=3)
    assert abs(lim - 10.2) < 1e-9                                      # 30 - 19.8


def test_samma_dygn_ersatter_dygnets_egen_topp():
    peaks = [(1, 8.0), (2, 7.0), (9, 6.0)]                             # idag (9) har redan 6 kW
    lim, info = ct.limit_kw(peaks, today=9, top_n=3)
    assert abs(lim - (10 * 3 - 15.0)) < 1e-9 and info["free_below_kw"] == 6.0


def test_tidigt_i_manaden_raknar_mot_malsteget():
    lim, info = ct.limit_kw([(1, 3.0)], today=2, top_n=3, target_kw=10)
    assert info["step"] == [5.0, 10.0] and lim == 27.0                 # 10*3 - (3+0)
    lim, info = ct.limit_kw([(1, 3.0)], today=2, top_n=3)              # utan mål: lägsta steget (2 kW)
    assert lim == 3.0


# --- Vikt per timme (natt 22-06), idé från FTW:s effektkontrakt ---

def test_vikt_galler_nattimmar_och_standard_ar_ingen_viktning():
    assert ct.hour_weight(23, 0.5) == 0.5 and ct.hour_weight(0, 0.5) == 0.5 and ct.hour_weight(5, 0.5) == 0.5
    assert ct.hour_weight(6, 0.5) == 1.0 and ct.hour_weight(21, 0.5) == 1.0 and ct.hour_weight(12, 0.5) == 1.0
    for ok in (None, "x", 1, 1.0, -0.1, 1.5):
        assert ct.hour_weight(23, ok) == 1.0                            # utan giltigt val: ingen viktning
    assert ct.hour_weight(23, 0) == 0.0                                  # 0 = natten räknas inte alls


def test_weigh_viktar_bara_natt_och_behaller_okanda_varden():
    hours = [(1, 23, 8.0), (1, 12, 4.0), (2, 3, 6.0), (3, 9, None)]
    assert ct.weigh(hours, 0.5) == [(1, 4.0), (1, 4.0), (2, 3.0), (3, None)]
    assert ct.weigh(hours, 1.0) == [(1, 8.0), (1, 4.0), (2, 6.0), (3, None)]


def test_viktad_topplista_ger_annat_steg():
    # utan vikt: 8, 7, 6 -> snitt 7 (steg 5-10). Med natthalva (8 och 6 var nattimmar): 4, 7, 3 -> snitt 4.67 (steg 2-5)
    hours = [(1, 23, 8.0), (2, 12, 7.0), (3, 2, 6.0)]
    _, plain = ct.limit_kw(ct.weigh(hours, 1.0), today=9, top_n=3)
    _, weighted = ct.limit_kw(ct.weigh(hours, 0.5), today=9, top_n=3)
    assert plain["step"] == [5.0, 10.0] and weighted["step"] == [2.0, 5.0]


def test_gransen_for_nattimmen_delas_med_vikten():
    peaks = [(1, 7.5), (2, 4.0), (3, 8.0)]                              # som test_granssnittet_stannar_i_steget: 14,5 kW
    lim, info = ct.limit_kw(peaks, today=9, top_n=3, weight_now=0.5)
    assert abs(lim - 29.0) < 1e-9 and info["weight_now"] == 0.5          # bara hälften räknas: dubbelt så hög gräns
    lim, _ = ct.limit_kw(peaks, today=9, top_n=3, weight_now=1.0)
    assert abs(lim - 14.5) < 1e-9


def test_vikt_noll_ger_ingen_gräns_och_ogiltig_vikt_ar_ingen_viktning():
    peaks = [(1, 7.5), (2, 4.0), (3, 8.0)]
    lim, info = ct.limit_kw(peaks, today=9, top_n=3, weight_now=0)
    assert lim == float("inf") and info["limit_kw"] is None
    for bad in (None, "x", -1, 2):
        lim, _ = ct.limit_kw(peaks, today=9, top_n=3, weight_now=bad)
        assert abs(lim - 14.5) < 1e-9


def test_utan_vikt_ar_allt_som_forut():
    peaks = [(1, 9.9), (2, 9.9), (3, 9.0)]
    assert ct.limit_kw(peaks, today=9, top_n=3) == ct.limit_kw(peaks, today=9, top_n=3, weight_now=1.0)


def test_riktiga_endpointen_sparar_nattvikten_och_nekar_ogiltigt(monkeypatch):
    import ast
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    import ew_settings
    from starlette.responses import JSONResponse
    node = next(n for n in ast.parse((Path(__file__).resolve().parents[1] / "webdashboard/app.py").read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "capacity_tariff_set")
    node.decorator_list = []
    role = ["owner"]
    writes = []
    monkeypatch.setattr(ew_settings, "update", lambda **kw: writes.append(kw))
    scope = {"Request": object, "JSONResponse": JSONResponse, "AUTH": SimpleNamespace(session=lambda r: (role[0], "user")),
             "ew_settings": ew_settings}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), scope)

    class Request:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    call = lambda body: asyncio.run(scope[node.name](Request(body)))
    assert call({"enabled": True, "night_weight_pct": 50})["ok"] is True
    assert writes[-1]["capacity_tariff"]["night_weight"] == 0.5
    call({"enabled": True, "night_weight_pct": "37,5"})
    assert writes[-1]["capacity_tariff"]["night_weight"] == 0.375           # kommatecken som decimaltecken
    call({"enabled": True})
    assert writes[-1]["capacity_tariff"]["night_weight"] == 1.0              # inget val = ingen viktning (som förut)
    call({"enabled": True, "night_weight_pct": ""})
    assert writes[-1]["capacity_tariff"]["night_weight"] == 1.0
    n = len(writes)
    for bad in (150, -5, "x"):
        assert call({"enabled": True, "night_weight_pct": bad}).status_code == 400
    assert len(writes) == n                                                   # inget sparas vid fel
    role[0] = "family"
    assert call({"enabled": True, "night_weight_pct": 50}).status_code == 403
    assert len(writes) == n
