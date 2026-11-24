"""Veckobrevet i appen (smartbox/news_signup.py): anmälan går bara till samlaren, bara ägaren når ändpunkterna, inget hus-ID skickas."""
import ast
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ew_settings
import news_signup as ns
import telemetry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "energywizard.json"))
    ew_settings._cache.update(mtime=None, data={})
    return tmp_path


def _resp(status=200, json=None):
    r = MagicMock(status_code=status, ok=status < 400)
    r.json.return_value = json or {}
    return r


def test_giltig_adress_kontroll():
    assert ns.valid_email("anna@example.com") and ns.valid_email("a.b+c@sub.example.se")
    for bad in ("", None, "x", "a@b", "a b@example.com", "a@@example.com", "a@example..com", ".a@example.com", "<a>@example.com", "a@-x.com", "a@example.c", "a" * 300 + "@example.com"):
        assert not ns.valid_email(bad), bad


def test_anmalan_skickar_bara_adress_och_sprak_och_sparar_vantande(cfg, monkeypatch):
    seen = {}
    def post(url, json=None, timeout=None):
        seen.update(url=url, json=json)
        return _resp(200, {"ok": True, "t": "hemlig"})
    monkeypatch.setattr(ns.requests, "post", post)
    r = ns.subscribe(" Anna@Example.com ", "sv-SE")
    assert r == {"status": "pending", "email": "anna@example.com"}
    assert seen["url"] == telemetry.ENDPOINT + "/news/subscribe"
    assert seen["json"] == {"email": "anna@example.com", "lang": "sv"}              # inget hus-ID, ingen version, ingen plats
    assert ns.state() == {"status": "pending", "email": "anna@example.com", "dismissed": True}


def test_redan_bekraftad_ger_ingen_hemlighet_och_fel_ger_begripliga_texter(cfg, monkeypatch):
    monkeypatch.setattr(ns.requests, "post", lambda *a, **k: _resp(200, {"ok": True, "already": True}))
    assert ns.subscribe("a@example.com", "en")["status"] == "confirmed"
    assert "token" not in ew_settings.get(ns.KEY)
    for status, text in ((429, "Vänta några minuter"), (400, "giltig e-postadress"), (502, "Kunde inte skicka")):
        monkeypatch.setattr(ns.requests, "post", lambda *a, _s=status, **k: _resp(_s))
        with pytest.raises(ns.NewsError, match=text):
            ns.subscribe("b@example.com", "en")
    monkeypatch.setattr(ns.requests, "post", MagicMock(side_effect=OSError("nere")))
    with pytest.raises(ns.NewsError, match="nå servern"):
        ns.subscribe("b@example.com", "en")
    with pytest.raises(ns.NewsError, match="giltig"):
        ns.subscribe("inte-en-adress", "en")                                         # nekas redan här, ingen förfrågan


def test_status_uppdateras_fran_samlaren_och_avregistrering_via_mejl_syns(cfg, monkeypatch):
    monkeypatch.setattr(ns.requests, "post", lambda *a, **k: _resp(200, {"ok": True, "t": "tok"}))
    ns.subscribe("a@example.com", "en")
    monkeypatch.setattr(ns.requests, "get", lambda *a, **k: _resp(200, {"status": "confirmed"}))
    assert ns.state(refresh=True)["status"] == "confirmed" and ns.state()["status"] == "confirmed"
    monkeypatch.setattr(ns.requests, "get", MagicMock(side_effect=OSError("nere")))
    assert ns.state(refresh=True)["status"] == "confirmed"                          # samlaren onåbar: visa det vi vet
    ew_settings.update(**{ns.KEY: {"email": "a@example.com", "token": "tok", "status": "pending", "dismissed": True}})
    monkeypatch.setattr(ns.requests, "get", lambda *a, **k: _resp(200, {"status": "none"}))   # avregistrerad via mejlet
    assert ns.state(refresh=True) == {"status": "none", "email": None, "dismissed": True}


def test_avsluta_raderar_hos_samlaren_och_rensar_lokalt(cfg, monkeypatch):
    posts = []
    monkeypatch.setattr(ns.requests, "post", lambda url, json=None, timeout=None: (posts.append((url, json)), _resp(200, {"ok": True, "t": "tok"}))[1])
    ns.subscribe("a@example.com", "en")
    assert ns.cancel() == {"status": "none", "email": None}
    assert posts[-1] == (telemetry.ENDPOINT + "/news/cancel", {"t": "tok"})
    assert ns.state() == {"status": "none", "email": None, "dismissed": True}
    monkeypatch.setattr(ns.requests, "post", MagicMock(side_effect=OSError("nere")))
    ew_settings.update(**{ns.KEY: {"email": "a@example.com", "token": "tok", "status": "pending"}})
    with pytest.raises(ns.NewsError):
        ns.cancel()
    assert ns.state()["status"] == "pending"                                         # misslyckad radering lämnar läget som det var


def test_dismiss_doar_raden_utan_att_andra_anmalan(cfg):
    assert ns.state() == {"status": "none", "email": None, "dismissed": False}
    assert ns.dismiss()["dismissed"] is True


@pytest.mark.parametrize("path,names", [("ewapp/app.py", ("news_state", "news_subscribe", "news_cancel", "news_dismiss")),
                                        ("webdashboard/app.py", ("api_news_state", "api_news_subscribe", "api_news_cancel"))])
def test_alla_nyhetsandpunkter_kraver_agaren(path, names):
    src = (ROOT / path).read_text(encoding="utf-8")
    funcs = {n.name: ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in names:
        body = funcs[n]
        assert ('_role(request) != "owner"' in body) or ("_news_guard(request)" in body), n
        assert body.index("news_signup") > body.index("owner") if "owner" in body else body.index("news_signup") > body.index("_news_guard")


def test_nyhetsflodet_cachar_rensar_och_faller_tillbaka(monkeypatch):
    import news_feed as nf
    nf._cache.clear()
    calls = []
    def get_ok(url, params=None, timeout=None):
        calls.append(params)
        return _resp(200, {"issues": [{"id": "2026-w48", "period": "p", "versions": "v", "items": [["a", "b"]], "extra": "ignoreras"}, "skräp"]})
    t = [1000.0]
    got = nf.issues("sv", get=get_ok, now=lambda: t[0])
    assert got == [{"id": "2026-w48", "period": "p", "versions": "v", "items": [["a", "b"]]}] and calls == [{"lang": "sv", "limit": 8}]
    nf.issues("sv", get=get_ok, now=lambda: t[0] + 60)
    assert len(calls) == 1                                                       # cachat i fem minuter
    boom = MagicMock(side_effect=OSError("nere"))
    assert nf.issues("sv", get=boom, now=lambda: t[0] + 1000) == got            # samlaren nere: senast hämtade
    assert nf.issues("xx", get=boom, now=lambda: t[0]) == []                    # inget hämtat än: tom lista
    assert nf.issues("xx", get=get_ok, now=lambda: t[0] + 2000)[0]["id"] == "2026-w48" and calls[-1]["lang"] == "en"      # okänt språk -> engelska


def test_nyhetsflodet_kraver_inloggning_men_inte_agare():
    for path, name in (("ewapp/app.py", "news_issues"), ("webdashboard/app.py", "api_news_issues")):
        src = (ROOT / path).read_text(encoding="utf-8")
        body = {n.name: ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}[name]
        assert ("_ok(request)" in body or "role is None" in body) and '"owner"' not in body, name
        assert body.index("news_feed") > body.index("_ok(request)" if "_ok(request)" in body else "role is None")
