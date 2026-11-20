"""#457: poolen ska inte lämna ut en anslutning som Postgres redan stängt.

Om läsningen ändå bryts mitt i frågan är det PR #523 som provar igen och behåller senast lästa
inställningar. Den här filen täcker bara kontrollen före frågan.
"""
import psycopg_pool

import logger
import settings


def test_settings_pool_checks_connection_before_use(monkeypatch):
    ping = psycopg_pool.ConnectionPool.check_connection
    seen = {}

    class Recording(psycopg_pool.ConnectionPool):
        def __init__(self, *args, **kwargs):
            seen["kwargs"] = kwargs

    monkeypatch.setattr(settings, "_pool", None)
    monkeypatch.setattr(settings, "ConnectionPool", Recording)
    settings.get_db_pool()
    assert seen["kwargs"]["check"] is ping
    assert seen["kwargs"]["open"] is True


def test_log_pool_checks_connection_before_use(monkeypatch):
    ping = psycopg_pool.ConnectionPool.check_connection
    seen = {}

    class Recording(psycopg_pool.ConnectionPool):
        def __init__(self, *args, **kwargs):
            seen["kwargs"] = kwargs

    monkeypatch.setattr(logger, "_pool", None)
    monkeypatch.setattr(logger, "ConnectionPool", Recording)
    logger.get_db_pool()
    assert seen["kwargs"]["check"] is ping
    assert seen["kwargs"]["open"] is True


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
