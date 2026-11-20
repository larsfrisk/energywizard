"""#457: avbruten Postgres-anslutning vid läsning av inställningar.

Förr loggades det som fel och varvet styrde på fabriksvärden (25 A säkring, effekttak på).
Nu provas anslutningen en gång till, och senast lästa värden behålls om även det misslyckas.
"""
from contextlib import contextmanager

import psycopg
from psycopg_pool import PoolTimeout

import settings

DROP = psycopg.OperationalError(
    "consuming input failed: server closed the connection unexpectedly\n"
    "\tThis probably means the server terminated abnormally\n"
    "\tbefore or while processing the request."
)


class _Cur:
    description = [("id",), ("indoor_min",), ("fuse_size_a",), ("peak_shaving_enabled",)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return (1, 20.4, 16, False)


class _Conn:
    def cursor(self):
        return _Cur()


def _ok():
    @contextmanager
    def cm():
        yield _Conn()
    return cm()


def test_ett_avbrott_lasas_om(monkeypatch, capsys):
    settings._last_settings = None
    calls = []

    def get_db(timeout=None):
        calls.append(timeout)
        if len(calls) == 1:
            raise DROP
        return _ok()

    monkeypatch.setattr(settings, "get_db", get_db)
    got = settings.get_settings()
    assert calls == [None, settings._SETTINGS_RETRY_S]
    assert got["indoor_min"] == 20.4
    assert got["fuse_size_a"] == 16.0
    assert got["peak_shaving_enabled"] is False
    assert "❌" not in capsys.readouterr().out
    got["indoor_min"] = 1
    assert settings._last_settings["indoor_min"] == 20.4


def test_tva_avbrott_behaller_senast_lasta(monkeypatch, capsys):
    settings._last_settings = {"indoor_min": 18.0, "fuse_size_a": 16.0, "peak_shaving_enabled": False}
    calls = []

    def get_db(timeout=None):
        calls.append(timeout)
        raise DROP

    monkeypatch.setattr(settings, "get_db", get_db)
    got = settings.get_settings()
    assert calls == [None, settings._SETTINGS_RETRY_S]
    assert got["indoor_min"] == 18.0 and got["fuse_size_a"] == 16.0
    got["fuse_size_a"] = 99
    out = capsys.readouterr().out
    assert out.startswith("⚠️") and "❌" not in out
    assert settings.get_settings()["fuse_size_a"] == 16.0


def test_avbrott_utan_tidigare_lasning_ger_fabriksvarden(monkeypatch, capsys):
    settings._last_settings = None

    def get_db(timeout=None):
        raise DROP

    monkeypatch.setattr(settings, "get_db", get_db)
    got = settings.get_settings()
    assert got["indoor_min"] == 19.0 and got["fuse_size_a"] == 25.0
    assert got["peak_shaving_enabled"] is True
    assert "❌" in capsys.readouterr().out


def test_annat_fel_provar_inte_om_och_ger_fabriksvarden(monkeypatch, capsys):
    settings._last_settings = {"indoor_min": 18.0, "fuse_size_a": 16.0}
    calls = []

    def get_db(timeout=None):
        calls.append(timeout)
        raise ValueError("kolumnen saknas")

    monkeypatch.setattr(settings, "get_db", get_db)
    got = settings.get_settings()
    assert calls == [None]
    assert got["fuse_size_a"] == 25.0
    assert "❌" in capsys.readouterr().out


def test_pool_timeout_provar_inte_om(monkeypatch, capsys):
    settings._last_settings = {"fuse_size_a": 16.0}
    calls = []

    def get_db(timeout=None):
        calls.append(timeout)
        raise PoolTimeout("couldn't get a connection after 30.00 sec")

    monkeypatch.setattr(settings, "get_db", get_db)
    got = settings.get_settings()
    assert calls == [None]
    assert got["fuse_size_a"] == 25.0
    assert "❌" in capsys.readouterr().out
