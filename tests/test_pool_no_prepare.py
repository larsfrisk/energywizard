"""#585: "cached plan must not change result type" (FeatureNotSupported) i settings.get_settings. Postgres
förbereder en fråga efter fem körningar; lägger en uppgradering till en kolumn i tabellen felar sedan
SELECT * på den anslutningen för alltid. Poolerna ska aldrig förbereda frågor."""
import pytest


def _pool_query_survives_alter(get_db, db, table):
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute(f"CREATE TABLE {table} (id int, a int)")
    db.execute(f"INSERT INTO {table} VALUES (1, 2)")
    try:
        for _ in range(40):                     # poolen växlar mellan anslutningar; alla ska nå psycopgs gräns (5)
            with get_db() as c:
                c.execute(f"SELECT * FROM {table} WHERE id = 1").fetchone()
        db.execute(f"ALTER TABLE {table} ADD COLUMN extra int")   # som en uppgradering gör
        for _ in range(6):
            with get_db() as c:
                assert c.execute(f"SELECT * FROM {table} WHERE id = 1").fetchone() == (1, 2, None)
    finally:
        db.execute(f"DROP TABLE IF EXISTS {table}")


def test_inställningspoolen_klarar_ny_kolumn(db, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "DB_HOST", __import__("conftest").DB_HOST)
    monkeypatch.setattr(settings, "_pool", None)
    try:
        _pool_query_survives_alter(settings.get_db, db, "t585_settings")
    finally:
        settings._pool.close()


def test_loggpoolen_klarar_ny_kolumn(smartbox, db):
    import logger
    try:
        _pool_query_survives_alter(logger.get_db, db, "t585_logger")
    finally:
        logger._pool.close()
