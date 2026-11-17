"""#445: SQL calendars follow installation settings, independent of DB timezone."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import nordpool
from local_sql import local_sql


@pytest.mark.parametrize('zone,expected', [('Europe/Stockholm', '2026-11-17 00:30'),
    ('Europe/Prague', '2026-11-17 00:30'), ('Europe/Helsinki', '2026-11-17 01:30'),
    ('Australia/Sydney', '2026-11-17 10:30'), ('America/New_York', '2026-11-16 18:30')])
def test_actual_postgres_local_hour_and_day(db, monkeypatch, zone, expected):
    monkeypatch.setattr(nordpool, 'price_timezone', lambda: ZoneInfo(zone))
    query = local_sql("SELECT to_char(%(stamp)s::timestamptz AT TIME ZONE __EW_TIMEZONE__, 'YYYY-MM-DD HH24:MI')")
    assert '%(stamp)s' in query  # other values remain bound parameters
    stamp = datetime(2026, 11, 16, 23, 30, tzinfo=timezone.utc)
    assert db.execute(query, {'stamp': stamp}).fetchone()[0] == expected


def test_timezone_is_resolved_per_call_not_at_module_import(monkeypatch):
    query = 'SELECT now() AT TIME ZONE __EW_TIMEZONE__'
    for name in ['Europe/Prague', 'Australia/Sydney', 'Europe/Stockholm']:
        monkeypatch.setattr(nordpool, 'price_timezone', lambda: ZoneInfo(name))
        assert local_sql(query) == f"SELECT now() AT TIME ZONE '{name}'"
    assert local_sql('SELECT %s') == 'SELECT %s'


def test_timeline_hour_uses_same_zone_as_sql(monkeypatch):
    import timeline
    monkeypatch.setattr(nordpool, 'price_timezone', lambda: ZoneInfo('Australia/Sydney'))
    instant = datetime(2026, 11, 16, 23, 30, tzinfo=timezone.utc)
    hour = timeline._hour(instant)
    assert hour.isoformat() == '2026-11-17T10:00:00+11:00'


def test_saved_savings_template_uses_updated_zone(db, monkeypatch):
    import savings
    db.execute('CREATE TEMP TABLE sensor_log (timestamp timestamptz, price double precision, net_power double precision)')
    try:
        db.execute("INSERT INTO sensor_log VALUES ('2026-11-16 23:30+00', 1, 1000)")
        for zone, date, hour in [('Australia/Sydney', '2026-11-17', 10), ('America/New_York', '2026-11-16', 18)]:
            monkeypatch.setattr(nordpool, 'price_timezone', lambda: ZoneInfo(zone))
            sql = local_sql(savings._HOURLY_SQL).replace(':days', '%(days)s')
            row = db.execute(sql, {'days': 9999}).fetchone()
            assert row[0].isoformat() == date and row[1] == hour
    finally:
        db.execute('DROP TABLE pg_temp.sensor_log')


def test_invalid_timezone_cannot_be_interpolated(monkeypatch):
    monkeypatch.setattr(nordpool, 'price_timezone', lambda: type('Bad', (), {'key': "UTC'; DROP TABLE sensor_log; --"})())
    with pytest.raises((ValueError, KeyError)):
        local_sql('SELECT now() AT TIME ZONE __EW_TIMEZONE__')


@pytest.mark.parametrize('date,hours', [('2026-03-29', 23), ('2026-10-25', 25)])
def test_published_price_day_has_all_dst_quarters(db, monkeypatch, date, hours):
    import ha_publisher
    monkeypatch.setattr(nordpool, 'price_timezone', lambda: ZoneInfo('Europe/Prague'))
    db.execute('TRUNCATE elpriser')
    db.execute("""INSERT INTO elpriser SELECT t, 1 FROM generate_series(
        %s::date::timestamp AT TIME ZONE 'Europe/Prague',
        (%s::date + 1)::timestamp AT TIME ZONE 'Europe/Prague' - interval '15 minutes',
        interval '15 minutes') t""", (date, date))

    class Connection:
        def execute(self, statement):
            sql = str(statement).replace('now()', f"TIMESTAMPTZ '{date} 12:00:00+00'")
            assert '__EW_TIMEZONE__' not in sql
            return db.execute(sql)

    assert len(ha_publisher._day_prices(Connection(), 0)) == hours * 4
    assert ha_publisher._day_prices(Connection(), 1) == []


def test_no_remaining_literal_stockholm_sql():
    root = Path(__file__).resolve().parents[1]
    for folder in ['smartbox', 'ewapp', 'webdashboard']:
        for path in (root / folder).rglob('*.py'):
            assert "AT TIME ZONE 'Europe/Stockholm'" not in path.read_text(encoding='utf-8'), path
