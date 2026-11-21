"""#227: veckan i supportutdraget - en rad per dygn, bara siffror och sanerade felrader."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import support_bundle  # noqa: E402
import support_week  # noqa: E402

TZ = ZoneInfo("Europe/Stockholm")
UTC = timezone.utc
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=TZ)


def minute_rows(start, end, **kw):
    """En rad per minut från start (inkl.) till end (exkl.)."""
    d = dict(net=1000.0, pv=0.0, soc=None, ev1=0.0, ev2=0.0, comp=0, plan=None)
    d.update(kw)
    t = start
    while t < end:
        yield (t, d["net"], d["pv"], d["soc"], d["ev1"], d["ev2"], d["comp"], d["plan"])
        t += timedelta(minutes=1)


def local(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def test_one_line_per_day_and_energy_in_kwh():
    rows = list(minute_rows(local(2026, 11, 20), local(2026, 11, 21), net=1000.0, pv=2000.0, ev1=4.0, comp=1))
    out = support_week.summarize(rows, [], TZ, NOW)
    assert out[0].startswith("--- vecka")
    days = [l for l in out if l[:2] == "20"]
    assert len(days) == 7
    nov20 = next(l for l in days if l.startswith("2026-11-20"))
    assert "nät köpt 24.0 sålt 0.0" in nov20          # 1 kW i 24 h
    assert "sol 48.0" in nov20 and "bil 96.0" in nov20  # 2 kW och 4 kW i 24 h
    assert "VP 1440 min" in nov20 and "hål 0 (0 min)" in nov20
    today = next(l for l in days if l.startswith("2026-11-21"))
    assert "(pågår)" in today and "ingen data" in today   # idag har inga rader än


def test_days_without_data_say_so_and_cover_exactly_seven_days():
    out = support_week.summarize([], [], TZ, NOW)
    days = [l for l in out if l[:2] == "20"]
    assert [l[:10] for l in days] == [f"2026-11-{d}" for d in range(15, 22)]
    assert all("ingen data" in l for l in days)


def test_export_counts_as_sold_and_ev_in_watts_is_converted():
    rows = list(minute_rows(local(2026, 11, 20, 12), local(2026, 11, 20, 13), net=-3000.0, ev1=7400.0, ev2=0.0))
    out = support_week.summarize(rows, [], TZ, NOW)
    nov20 = next(l for l in out if l.startswith("2026-11-20"))
    assert "nät köpt 0.0 sålt 3.0" in nov20            # 3 kW i en timme
    assert "bil 7.4" in nov20                           # 7400 W loggat som W -> 7,4 kWh på en timme


def test_battery_range_split_into_day_and_night_and_plan_changes():
    rows = (list(minute_rows(local(2026, 11, 20, 23), local(2026, 11, 20, 23, 30), soc=20.0, plan=1))
            + list(minute_rows(local(2026, 11, 20, 23, 30), local(2026, 11, 21, 0, 0), soc=35.0, plan=2))
            + list(minute_rows(local(2026, 11, 20, 14), local(2026, 11, 20, 14, 10), soc=90.0, plan=2)))
    rows.sort(key=lambda r: r[0])
    nov20 = next(l for l in support_week.summarize(rows, [], TZ, NOW) if l.startswith("2026-11-20"))
    assert "batteri 20-90 %" in nov20
    assert "(natt 20-35)" in nov20                      # dagens 90 % syns inte i natten
    assert "planbyten 2" in nov20                       # 2 -> 1 -> 2 i tidsordning
    assert "inget batteri" in next(l for l in support_week.summarize(list(minute_rows(local(2026, 11, 20), local(2026, 11, 20, 1))), [], TZ, NOW) if l.startswith("2026-11-20"))


def test_gaps_in_the_minute_data_are_counted():
    rows = (list(minute_rows(local(2026, 11, 20, 10), local(2026, 11, 20, 10, 30)))
            + list(minute_rows(local(2026, 11, 20, 10, 40), local(2026, 11, 20, 11))))   # 10 minuter utan data
    nov20 = next(l for l in support_week.summarize(rows, [], TZ, NOW) if l.startswith("2026-11-20"))
    assert "hål 1 (10 min)" in nov20 or "hål 1 (9 min)" in nov20
    short = list(minute_rows(local(2026, 11, 20, 10), local(2026, 11, 20, 10, 5))) + list(minute_rows(local(2026, 11, 20, 10, 7), local(2026, 11, 20, 10, 10)))
    assert "hål 0" in next(l for l in support_week.summarize(short, [], TZ, NOW) if l.startswith("2026-11-20"))   # 2 min är inget hål


def test_dst_day_of_25_hours_counts_in_local_days():
    now = local(2026, 10, 26, 12)
    start = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)          # lokal midnatt (sommartid)
    rows = list(minute_rows(start, start + timedelta(hours=25), net=1000.0))
    out = support_week.summarize(rows, [], TZ, now)
    oct25 = next(l for l in out if l.startswith("2026-10-25"))
    assert "nät köpt 25.0" in oct25                      # dygnet har 25 timmar när klockan går tillbaka
    assert "hål 0" in oct25


def test_errors_and_warnings_per_day_and_most_common_errors_are_scrubbed():
    j = [(local(2026, 11, 20, 10), "fel", "❌ Fel på sensor.garage_temp"),
         (local(2026, 11, 20, 11), "fel", "❌ Fel på sensor.garage_temp"),
         (local(2026, 11, 20, 12), "fel", "❌ Något annat\nTraceback ..."),
         (local(2026, 11, 20, 13), "varning", "⚠️ Spabad offline"),
         (local(2026, 11, 20, 14), "info", "bara info"),
         (local(2026, 11, 10, 9), "fel", "för gammalt")]
    out = support_week.summarize(list(minute_rows(local(2026, 11, 20), local(2026, 11, 20, 1))), j, TZ, NOW,
                                 scrub=lambda s: s.replace("sensor.garage_temp", "sensor.<…>"))
    nov20 = next(l for l in out if l.startswith("2026-11-20"))
    assert "fel 3 varn 1" in nov20
    last = out[-1]
    assert last.startswith("vanligaste felen: 2x ❌ Fel på sensor.<…> ; 1x ❌ Något annat")
    assert "garage_temp" not in "\n".join(out) and "för gammalt" not in "\n".join(out)


def test_a_day_with_only_errors_is_still_listed():
    out = support_week.summarize([], [(local(2026, 11, 19, 8), "fel", "x")], TZ, NOW)
    assert next(l for l in out if l.startswith("2026-11-19")).endswith("ingen data | fel 1 varn 0")


def test_bad_values_never_break_the_summary():
    rows = [(local(2026, 11, 20, 10), None, float("nan"), "x", None, float("inf"), "?", None),
            (local(2026, 11, 20, 10, 1), 500.0, 100.0, 50.0, 0, 0, 1, 7)]
    out = support_week.summarize(rows, [], TZ, NOW)
    assert any(l.startswith("2026-11-20") and "batteri 50-50 %" in l for l in out)


def test_lines_is_empty_when_the_database_is_unavailable():
    import logger
    with mock.patch.object(logger, "get_db", side_effect=RuntimeError("db nere")):
        assert support_week.lines([]) == []


def test_bundle_carries_the_week_between_decisions_and_the_log(monkeypatch):
    support_bundle._ring.clear()
    monkeypatch.setattr(support_bundle, "enabled", lambda: True)
    monkeypatch.setattr(support_week, "lines", lambda words=None: ["--- vecka (test) ---", "2026-11-20 | nät köpt 1.0"])
    monkeypatch.setattr(support_bundle, "_journal_lines", lambda: [])
    out = support_bundle.build("m", "E")
    assert "--- vecka (test) ---\n2026-11-20 | nät köpt 1.0" in out
    assert out.index("module=m") < out.index("--- vecka")


def test_week_survives_a_truncated_bundle(monkeypatch):
    support_bundle._ring.clear()
    monkeypatch.setattr(support_bundle, "enabled", lambda: True)
    monkeypatch.setattr(support_week, "lines", lambda words=None: ["--- vecka (test) ---", "2026-11-20 | veckodata"])
    big = [(datetime(2026, 11, 21, 10, 0, tzinfo=TZ), "src", "info", "x" * 500) for _ in range(300)]
    monkeypatch.setattr(support_bundle, "_journal_lines", lambda: big)
    out = support_bundle.build("m", "E")
    assert len(out) <= support_bundle._MAX_BUNDLE
    assert "2026-11-20 | veckodata" in out                 # veckan ligger före loggen och trunkeras inte bort
