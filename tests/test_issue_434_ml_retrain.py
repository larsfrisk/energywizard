"""#434: med för lite data tränades sol- och baslastprofilerna om vid varje anrop (flera gånger i minuten, med en fråga
över ett års sensor_log). Ett tomt resultat gäller nu en timme."""
import os
import sys
from contextlib import contextmanager

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import pandas as pd
import learning


class _Cur:
    def execute(self, *a, **k): pass
    def fetchone(self): return ("x",)      # kolumnen finns; ingen sparad profil
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def cursor(self): return _Cur()
    def commit(self): pass


@contextmanager
def _db():
    yield _Conn()


def _run(monkeypatch, fn):
    calls = []
    monkeypatch.setattr(learning.sm_logger, "get_db", _db)
    monkeypatch.setattr(learning.pd, "read_sql", lambda *a, **k: calls.append(1) or pd.DataFrame())
    monkeypatch.setattr(learning, "_too_little_data_at", {}, raising=False)
    for _ in range(5):
        assert fn() == {}
    return len(calls)


def test_solprofilen_tränas_inte_om_varje_anrop(monkeypatch):
    monkeypatch.setattr(learning, "_cached_solar_profile", None, raising=False)
    assert _run(monkeypatch, learning.get_solar_profile) == 1


def test_baslastprofilen_tränas_inte_om_varje_anrop(monkeypatch):
    monkeypatch.setattr(learning, "_cached_base_load_profile", None, raising=False)
    assert _run(monkeypatch, learning.get_base_load_profile) == 1


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}
    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error", response=self)
    def json(self):
        return self._b


def test_ha_som_startar_om_ger_varning_och_nytt_försök(monkeypatch, capsys):
    import homeassistant
    svar = [_Resp(502), _Resp(200, {"internal_url": "http://ha.local:8123"})]
    monkeypatch.setattr(homeassistant.requests, "get", lambda *a, **k: svar.pop(0))
    assert homeassistant.get_own_base_url(retries=2, wait_s=0) == "http://ha.local:8123"
    assert "❌" not in capsys.readouterr().out


def test_502_hela_tiden_är_en_varning_inte_ett_fel(monkeypatch, capsys):
    import homeassistant
    monkeypatch.setattr(homeassistant.requests, "get", lambda *a, **k: _Resp(502))
    assert homeassistant.get_own_base_url(retries=1, wait_s=0) is None
    out = capsys.readouterr().out
    assert "❌" not in out and "⚠️" in out


def test_401_är_fortfarande_ett_fel(monkeypatch, capsys):
    import homeassistant
    monkeypatch.setattr(homeassistant.requests, "get", lambda *a, **k: _Resp(401))
    assert homeassistant.get_own_base_url() is None
    assert "❌" in capsys.readouterr().out
