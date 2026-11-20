"""#457: en anslutning som Postgres stängt ska inte bli standardinställningar och ett felärende."""
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

import logger
import settings


def _capture(monkeypatch):
    lines = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: lines.append(" ".join(map(str, args))))
    return lines


def _conn(hours):
    class Cur:
        description = [("cheap_hours_count",)]

        def fetchone(self):
            return (hours,)

        def execute(self, *_args, **_kwargs):
            return None

    class Conn:
        def cursor(self):
            return self

        def __enter__(self):
            return Cur()

        def __exit__(self, *_args):
            return False

    return Conn()


def _scripted(monkeypatch, outcomes):
    state = {"n": 0}

    @contextmanager
    def get_db():
        outcome = outcomes[state["n"]]
        state["n"] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        yield outcome

    monkeypatch.setattr(settings, "get_db", get_db)
    return state


def test_pool_checks_connection_before_use(monkeypatch):
    ping = ConnectionPool.check_connection
    seen = {}

    class Recording(ConnectionPool):
        def __init__(self, *args, **kwargs):
            seen["kwargs"] = kwargs

    monkeypatch.setattr(settings, "_pool", None)
    monkeypatch.setattr(settings, "ConnectionPool", Recording)
    settings.get_db_pool()
    assert seen["kwargs"]["check"] is ping
    assert seen["kwargs"]["min_size"] == 1
    assert seen["kwargs"]["open"] is True


def test_log_pool_checks_connection_before_use(monkeypatch):
    ping = ConnectionPool.check_connection
    seen = {}

    class Recording(ConnectionPool):
        def __init__(self, *args, **kwargs):
            seen["kwargs"] = kwargs

    monkeypatch.setattr(logger, "_pool", None)
    monkeypatch.setattr(logger, "ConnectionPool", Recording)
    logger.get_db_pool()
    assert seen["kwargs"]["check"] is ping
    assert seen["kwargs"]["open"] is True


def test_dropped_connection_is_read_again(monkeypatch):
    lines = _capture(monkeypatch)
    state = _scripted(monkeypatch, [
        psycopg.OperationalError(
            "consuming input failed: server closed the connection unexpectedly"),
        _conn(4),
    ])
    result = settings.get_settings()
    assert state["n"] == 2
    assert result["cheap_hours_count"] == 4
    assert any(line.startswith("⚠️") for line in lines)
    assert not any(line.startswith("❌") for line in lines)


def test_second_drop_stays_an_error(monkeypatch):
    lines = _capture(monkeypatch)
    state = _scripted(monkeypatch, [
        psycopg.OperationalError("server closed the connection unexpectedly"),
        psycopg.OperationalError("server closed the connection unexpectedly"),
    ])
    result = settings.get_settings()
    assert state["n"] == 2
    assert result["cheap_hours_count"] == 8
    assert any(line.startswith("❌ Fel vid läsning av inställningar") for line in lines)
    assert not any(line.startswith("⚠️") for line in lines)


def test_other_errors_are_not_retried(monkeypatch):
    lines = _capture(monkeypatch)
    state = _scripted(monkeypatch, [ValueError("trasig rad")])
    result = settings.get_settings()
    assert state["n"] == 1
    assert result["fuse_size_a"] == 25.0
    assert any("❌" in line for line in lines)


def test_pool_timeout_and_disk_full_are_not_retried(monkeypatch):
    lines = _capture(monkeypatch)
    state = _scripted(monkeypatch, [PoolTimeout("couldn't get a connection after 30.00 sec")])
    settings.get_settings()
    assert state["n"] == 1
    assert any("❌" in line for line in lines)

    lines.clear()
    state2 = _scripted(monkeypatch, [psycopg.errors.DiskFull("could not extend file")])
    settings.get_settings()
    assert state2["n"] == 1
    assert any("❌" in line for line in lines)


def test_closed_interface_is_retried(monkeypatch):
    _capture(monkeypatch)
    state = _scripted(monkeypatch, [psycopg.InterfaceError("the connection is closed"), _conn(6)])
    result = settings.get_settings()
    assert state["n"] == 2
    assert result["cheap_hours_count"] == 6


def test_terminated_backend_is_replaced(db, monkeypatch):
    """Postgres stänger en ledig anslutning. Nästa lån ska få en ny, inte det fel som #457 rapporterar."""
    monkeypatch.setattr(settings, "_pool", None)
    monkeypatch.setattr(settings, "DB_HOST", f"{db.info.host} port={db.info.port}")
    monkeypatch.setattr(settings, "DB_USER", db.info.user)
    monkeypatch.setattr(settings, "DB_NAME", db.info.dbname)
    pool = settings.get_db_pool()
    try:
        with settings.get_db() as conn:
            pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert db.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0] is True
        with settings.get_db() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
            assert conn.execute("SELECT pg_backend_pid()").fetchone()[0] != pid
    finally:
        pool.close()
