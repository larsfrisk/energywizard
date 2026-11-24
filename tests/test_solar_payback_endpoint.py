"""API:t för solcellernas återbetalning (webdashboard/app.py, #599 och #602): bara ägaren får skriva, felaktiga uppgifter ger
400 med en förklaring, och inskrivna månader sparas i inställningsfilen. Databasen och inställningsfilen ersätts; formlerna
testas i test_solar_payback.py."""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webdashboard"))
sys.path.insert(0, str(ROOT / "smartbox"))
CSV = ("manad;producerat_kwh;salt_kwh;kopt_kwh;kopt_pris_ore;salj_pris_ore;energiskatt_ore;overforing_ore;natnytta_ore;skattereduktion_ore\n"
       "2025-06;1000;700;300;100;40;49;30;3;60\n")


def _app():
    for k, v in (("POSTGRES_USER", "u"), ("POSTGRES_PASSWORD", "p"), ("POSTGRES_DB", "d")):
        os.environ.setdefault(k, v)
    sys.modules.pop("app", None)
    cwd = os.getcwd()
    os.chdir(ROOT / "webdashboard")
    try:
        return importlib.import_module("app")
    finally:
        os.chdir(cwd)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

    async def json(self):
        return self._b


@pytest.fixture
def mod(monkeypatch, tmp_path):
    m = _app()
    store = {}
    monkeypatch.setattr(m.ew_settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(m.ew_settings, "update", lambda **kw: store.update(kw))
    m._store = store
    m._role = "owner"
    monkeypatch.setattr(m.AUTH, "session", lambda request: (m._role, "x"))
    return m


def _body(resp):
    return json.loads(resp.body)


def test_bara_agaren_far_skriva(mod):
    mod._role = "guest"
    for fn, body in ((mod.api_solar_payback_settings, {"investment_kr": 1000, "start_date": "2024-01-01"}),
                     (mod.api_solar_payback_history, {"csv": CSV})):
        r = asyncio.run(fn(Req(body)))
        assert r.status_code == 403
    assert mod._store == {}


def test_felaktiga_uppgifter_ger_400_och_sparas_inte(mod):
    r = asyncio.run(mod.api_solar_payback_settings(Req({"investment_kr": 0, "start_date": "igår"})))
    assert r.status_code == 400 and _body(r)["errors"] and mod._store == {}
    r = asyncio.run(mod.api_solar_payback_history(Req({"csv": "a;b\n1;2"})))
    assert r.status_code == 400 and "Saknar kolumn" in _body(r)["detail"] and mod._store == {}


def test_uppgifter_och_manader_sparas_och_slas_ihop(mod):
    assert asyncio.run(mod.api_solar_payback_settings(Req({"investment_kr": "50 000", "start_date": "2025-01-01", "tax_credit_ore": 60,
                                                          "tax_credit_last_date": "2025-12-31"}))) == {"ok": True}
    st = mod._store["solar_payback"]
    assert st["investment_kr"] == 50000 and st["tax_credit_last_date"] == "2025-12-31"
    prev = asyncio.run(mod.api_solar_payback_history(Req({"csv": CSV, "preview": True})))
    assert prev["rows"] == 1 and "history" not in mod._store["solar_payback"]                # förhandsgranskning sparar inget
    assert asyncio.run(mod.api_solar_payback_history(Req({"csv": CSV})))["total"] == 1
    other = CSV.replace("2025-06", "2025-07")
    assert asyncio.run(mod.api_solar_payback_history(Req({"csv": other})))["total"] == 2     # läggs till
    assert asyncio.run(mod.api_solar_payback_history(Req({"csv": other, "replace": True})))["total"] == 1   # ersätter allt
    assert [r["manad"] for r in mod._store["solar_payback"]["history"]] == ["2025-07"]
    assert mod._store["solar_payback"]["investment_kr"] == 50000                               # övriga uppgifter orörda


def test_get_bygger_svaret_med_inskrivna_manader(mod, monkeypatch):
    asyncio.run(mod.api_solar_payback_settings(Req({"investment_kr": 50000, "start_date": "2025-01-01", "tax_credit_ore": 60,
                                                   "tax_credit_last_date": "2025-12-31"})))
    asyncio.run(mod.api_solar_payback_history(Req({"csv": CSV})))
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    mod.ENGINE = engine
    import solar_payback
    monkeypatch.setattr(solar_payback, "load_frozen", lambda c: {})
    monkeypatch.setattr(solar_payback, "ew_months", lambda *a, **k: ([], (1.0, 1.0, 0)))
    out = asyncio.run(mod.api_solar_payback(Req()))
    assert out["ok"] is True and out["owner"] is True and out["history_months"] == 1
    assert out["summary"]["total_kr"] == pytest.approx(300 * (100 + 49 + 30) / 100 + 700 * (40 + 3) / 100 + 700 * 60 / 100)   # 537 + 301 + 420
    assert out["csv_columns"][0] == "manad"
