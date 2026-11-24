"""Solcellernas återbetalning (smartbox/solar_payback.py, #599 och #602): formlerna, CSV-importen, kalibreringen mot
inskrivna månader och SQL:en mot en riktig databas. Siffrorna i de rena testerna är räknade för hand i kommentarerna."""
import os
import sys
from datetime import date, datetime

import psycopg
import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
import solar_payback as sp  # noqa: E402

LAST = "2025-12-31"


def _row(month, prod, sold, buy=100.0, sell=40.0, tax=49.0, grid=30.0, nn=3.0, credit=60.0, bought=0.0):
    return {"manad": month, "producerat_kwh": prod, "salt_kwh": sold, "kopt_kwh": bought, "kopt_pris_ore": buy,
            "salj_pris_ore": sell, "energiskatt_ore": tax, "overforing_ore": grid, "natnytta_ore": nn, "skattereduktion_ore": credit}


# ---- formlerna ---------------------------------------------------------------------------------------------------
def test_manad_med_skattereduktion_raknad_for_hand():
    """1000 producerat, 700 sålt -> egenanvänt 300. Besparing 300 × (100 + 49 + 30) / 100 = 537. Intäkt 700 × (40 + 3) / 100 =
    301. Skattereduktion 700 × 60 / 100 = 420. Summa 1258."""
    r = sp.from_history_row(_row("2025-06", 1000, 700), LAST)
    assert r["own_kwh"] == 300
    assert r["saving_kr"] == pytest.approx(537.0)
    assert r["income_kr"] == pytest.approx(301.0)
    assert r["tax_credit_kr"] == pytest.approx(420.0)
    assert r["benefit_kr"] == pytest.approx(1258.0)


def test_skattereduktionen_slutar_efter_slutdatumet():
    """Samma månad efter 2025-12-31 ger ingen skattereduktion (den togs bort 2026-01-01): 1258 - 420 = 838."""
    r = sp.from_history_row(_row("2026-06", 1000, 700), LAST)
    assert r["tax_credit_kr"] == 0 and r["benefit_kr"] == pytest.approx(838.0)


def test_slutdatumets_gransfall():
    assert sp.tax_credit_applies("2025-12", "2025-12-31") is True       # månadens sista dag = slutdatumet
    assert sp.tax_credit_applies("2026-01", "2025-12-31") is False
    assert sp.tax_credit_applies("2025-12", "2025-12-30") is False      # slutdatum mitt i månaden: hela månaden gäller inte
    assert sp.tax_credit_applies("2025-12", None) is False and sp.tax_credit_applies("2025-12", "skräp") is False


def test_mer_sålt_än_producerat_ger_ingen_negativ_egenanvandning():
    r = sp.compute_month("2025-06", 100, 120, 100, 40, 79, 3, 60, LAST)
    assert r["own_kwh"] == 0 and r["saving_kr"] == 0


# ---- CSV-importen ------------------------------------------------------------------------------------------------
CSV = ("manad;producerat_kwh;salt_kwh;kopt_kwh;kopt_pris_ore;salj_pris_ore;energiskatt_ore;overforing_ore;natnytta_ore;"
       "skattereduktion_ore\n2023-02;276;147,47;1612,17;191,2;70,96;49;25,84;8,33;60\n2023-03;744;441,62;1692,87;185;86,36;49;25,84;8,33;60\n")


def test_csv_med_semikolon_och_decimalkomma():
    rows, errors = sp.parse_history_csv(CSV)
    assert errors == [] and [r["manad"] for r in rows] == ["2023-02", "2023-03"]
    assert rows[0]["salt_kwh"] == 147.47 and rows[0]["kopt_pris_ore"] == 191.2 and rows[0]["producerat_kwh"] == 276


def test_csv_rubrikerna_avgor_ordningen_och_tabb_funkar():
    head = "overforing_ore\tmanad\tproducerat_kwh\tsalt_kwh\tkopt_kwh\tkopt_pris_ore\tsalj_pris_ore\tenergiskatt_ore\n"
    rows, errors = sp.parse_history_csv("﻿" + head + "25.84\t2024-05\t2310\t1893\t520\t120\t18.7\t53.5\n")
    assert errors == [] and rows[0]["overforing_ore"] == 25.84 and rows[0]["manad"] == "2024-05"
    assert rows[0]["skattereduktion_ore"] == 0.0               # valfria kolumner saknas -> noll


@pytest.mark.parametrize("line,why", [
    ("2023-13;276;100;0;1;1;1;1;1;0", "ÅÅÅÅ-MM"),                       # månad 13
    ("2023-02;-5;100;0;1;1;1;1;1;0", "producerat_kwh"),                 # negativt
    ("2023-02;abc;100;0;1;1;1;1;1;0", "producerat_kwh"),                # text i talfält
    ("2023-02;100;500;0;1;1;1;1;1;0", "mer än producerat"),             # såldes mer än som producerades
    ("2023-02;100;50;0;;1;1;1;1;0", "kopt_pris_ore"),                   # tomt obligatoriskt fält
])
def test_csv_felaktiga_rader_ger_fel_med_radnummer_och_tas_inte_med(line, why):
    head = ";".join(sp.CSV_COLUMNS)
    rows, errors = sp.parse_history_csv(head + "\n" + line + "\n2023-03;744;441;0;1;1;1;1;1;0\n")
    assert [r["manad"] for r in rows] == ["2023-03"]
    assert len(errors) == 1 and errors[0].startswith("Rad 2") and why in errors[0]


def test_csv_tom_eller_utan_rubriker_och_dubblett():
    assert sp.parse_history_csv("")[1] == ["Filen är tom"]
    assert "Saknar kolumn" in sp.parse_history_csv("a;b\n1;2\n")[1][0]
    head = ";".join(sp.CSV_COLUMNS)
    rows, errors = sp.parse_history_csv(f"{head}\n2023-03;100;50;0;1;1;1;1;1;0\n2023-03;200;60;0;1;1;1;1;1;0\n")
    assert len(rows) == 1 and rows[0]["producerat_kwh"] == 200 and "två gånger" in errors[0]


def test_inställningar_valideras():
    ok, errs = sp.validate_settings({"investment_kr": "197250", "start_date": "2023-02-14", "tax_credit_ore": "60",
                                     "tax_credit_last_date": "2025-12-31", "natnytta_ore": "2,1"})
    assert errs == [] and ok["investment_kr"] == 197250 and ok["natnytta_ore"] == 2.1 and ok["tax_credit_last_date"] == "2025-12-31"
    _, errs = sp.validate_settings({"investment_kr": "0", "start_date": "igår", "tax_credit_ore": "900"})
    assert len(errs) == 3
    ok, errs = sp.validate_settings({"investment_kr": "1000", "start_date": "2024-01-01"})
    assert errs == [] and ok["tax_credit_last_date"] == "" and ok["tax_credit_ore"] == 0


# ---- sammanfattning ------------------------------------------------------------------------------------------------
def _months(n, benefit=1000.0, start=(2024, 1)):
    out, y, m = [], start[0], start[1]
    for _ in range(n):
        out.append({"month": f"{y}-{m:02d}", "benefit_kr": benefit, "produced_kwh": 100.0, "sold_kwh": 60.0, "own_kwh": 40.0,
                    "saving_kr": 400.0, "income_kr": 300.0, "tax_credit_kr": 300.0})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_sammanfattning_tid_kvar_ar_kvar_delat_med_senaste_tolv_manaderna():
    """18 månader × 1000 = 18 000 av 30 000. Kvar 12 000. De 12 sista månaderna gav 12 000 -> 1,0 år kvar."""
    months = _months(18)
    for r in months[:6]:
        r["benefit_kr"] = 3000.0                       # tidigt höga månader ska inte höja snittet framåt
    s = sp.summarize(months, 30000)
    assert s["total_kr"] == 6 * 3000 + 12 * 1000 and s["last12_kr"] == 12000
    assert s["remaining_kr"] == 0 and s["paid_back_pct"] == 100.0 and s["years_left"] == 0.0
    s = sp.summarize(months, 60000)
    assert s["remaining_kr"] == 30000 and s["years_left"] == 2.5 and s["paid_back_pct"] == 50.0


def test_sammanfattning_ar_for_ar_och_inget_ar_an():
    s = sp.summarize(_months(14), 100000)
    assert [y["year"] for y in s["years"]] == ["2024", "2025"] and [y["months"] for y in s["years"]] == [12, 2]
    assert s["years"][0]["benefit_kr"] == 12000 and s["years"][0]["own_pct"] == 40.0
    assert s["series"][-1]["cumulative_kr"] == 14000
    short = sp.summarize(_months(5), 100000)
    assert short["years_left"] is None and short["last12_kr"] is None      # under ett år: ingen prognos
    assert sp.summarize([], 0)["years_left"] is None and sp.summarize([], 0)["paid_back_pct"] is None


# ---- kalibreringen ---------------------------------------------------------------------------------------------------
def _raw(month, prod, sold, cov=1.0, opened=False, buy=1.5, sell=0.4):
    return {"month": month, "produced_kwh": prod, "sold_kwh": sold, "bought_kwh": 0.0, "coverage": cov,
            "buy_kr_kwh": buy, "sell_kr_kwh": sell, "open": opened}


def _hist(month, prod, sold):
    return {"month": month, "produced_kwh": prod, "sold_kwh": sold}


def test_kalibrering_ger_faktorerna_ur_manader_som_finns_i_bada():
    raws = [_raw("2026-06", 1000, 800), _raw("2026-07", 2000, 1600), _raw("2026-08", 1000, 800)]
    hist = [_hist("2026-06", 1050, 780), _hist("2026-07", 2100, 1560), _hist("2026-08", 1050, 780)]
    kp, ks, n = sp.calibrate(raws, hist)
    assert (round(kp, 3), round(ks, 3), n) == (1.05, 0.975, 3)         # 4200/4000 och 3120/3200


def test_kalibrering_kraver_tre_manader_nästan_hela_loggen_och_rimliga_faktorer():
    raws = [_raw("2026-06", 1000, 800), _raw("2026-07", 1000, 800)]
    assert sp.calibrate(raws, [_hist("2026-06", 1100, 780), _hist("2026-07", 1100, 780)]) == (1.0, 1.0, 2)   # bara två
    raws = [_raw(f"2026-0{i}", 1000, 800, cov=0.5) for i in (5, 6, 7)]
    assert sp.calibrate(raws, [_hist(r["month"], 1100, 780) for r in raws])[2] == 0                          # luckor
    raws = [_raw(f"2026-0{i}", 1000, 800) for i in (5, 6, 7)]
    assert sp.calibrate(raws, [_hist(r["month"], 3000, 780) for r in raws]) == (1.0, 1.0, 3)                 # faktor 3: fel i data
    raws = [_raw("2026-05", 1000, 800), _raw("2026-06", 1000, 800), _raw("2026-07", 1000, 800, opened=True),
            _raw("2026-08", 1000, 800)]
    assert sp.calibrate(raws, [_hist(r["month"], 1100, 780) for r in raws])[2] == 3                          # öppen månad räknas inte


def test_estimate_skalar_luckor_kalibrerar_och_ger_skattereduktion_bara_fore_slutdatumet():
    # 90 % av månaden finns: 900 producerat, 720 sålt -> uppskalat 1000 och 800. Kalibrering 1,05 och 0,975: 1050 och 780.
    r = sp.estimate(_raw("2025-06", 900, 720, cov=0.9), 1.05, 0.975, 3.0, 60.0, LAST)
    assert r["produced_kwh"] == pytest.approx(1050) and r["sold_kwh"] == pytest.approx(780) and r["scaled"] and r["calibrated"]
    assert r["own_kwh"] == pytest.approx(270)
    assert r["saving_kr"] == pytest.approx(270 * 1.5)                                  # viktat köppris i kr/kWh
    assert r["income_kr"] == pytest.approx(780 * (0.4 + 0.03))
    assert r["tax_credit_kr"] == pytest.approx(780 * 0.6)
    assert sp.estimate(_raw("2026-06", 900, 720, cov=0.9), 1, 1, 0, 60.0, LAST)["tax_credit_kr"] == 0


def test_pagaende_manad_skalas_inte():
    r = sp.estimate(_raw("2026-11", 100, 40, cov=0.3, opened=True), 1, 1, 0, 0, LAST)
    assert r["produced_kwh"] == 100 and not r["scaled"] and r["open"]


# ---- SQL mot en riktig databas ---------------------------------------------------------------------------------------
@pytest.fixture
def sl_conn(db):
    """Temporär sensor_log (bara den här sessionen) och fasta priser, så att ingenting i riktiga rader rörs."""
    params = dict(db.info.get_parameters())
    params["password"] = os.environ["POSTGRES_PASSWORD"]
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(**params))
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE sensor_log (timestamp TIMESTAMPTZ, price NUMERIC, net_power NUMERIC, pv_power_w NUMERIC)"))
            yield conn
    finally:
        engine.dispose()


@pytest.fixture
def flat_prices(monkeypatch):
    import nordpool
    monkeypatch.setattr(nordpool, "sql_buy_cost_expr", lambda col, tcol=None: f"({col} * 2.0)")
    monkeypatch.setattr(nordpool, "sql_sell_income_expr", lambda col: f"({col} * 0.5)")
    monkeypatch.setattr(nordpool, "price_timezone", lambda country=None: __import__("zoneinfo").ZoneInfo("Europe/Stockholm"))


def _fill(conn, start, minutes, pv, net, price=1.0, step=60):
    conn.execute(text("INSERT INTO sensor_log SELECT CAST(:s AS TIMESTAMPTZ) + make_interval(secs => g * :step), :p, :n, :pv "
                      "FROM generate_series(0, :m) g"), {"s": start, "p": price, "n": net, "pv": pv, "m": minutes, "step": step})


def test_sql_producerat_salt_och_egenanvant_per_manad_med_tidsviktning(sl_conn, flat_prices):
    # 121 rader med en minut emellan = 120 minuter (sista raden saknar nästa och räknas inte): 3000 W i 2 h = 6 kWh producerat.
    # Exporten 2000 W = 4 kWh sålt, egenanvänt 6 - 4 = 2 kWh. Pris 1 kr: köpt 2 kr/kWh, sålt 0,5 kr/kWh.
    _fill(sl_conn, "2026-05-10 12:00+02", 120, pv=3000, net=-2000)
    (raw,) = sp.ew_raw(sl_conn, date(2026, 1, 1), "2026-05")           # maj är "pågående": ingen uppskalning av luckan
    assert raw["month"] == "2026-05" and raw["produced_kwh"] == pytest.approx(6.0) and raw["sold_kwh"] == pytest.approx(4.0)
    assert raw["bought_kwh"] == pytest.approx(0.0) and raw["buy_kr_kwh"] == pytest.approx(2.0) and raw["sell_kr_kwh"] == pytest.approx(0.5)
    assert 0 < raw["coverage"] < 0.01 and raw["open"] is True
    r = sp.estimate(raw, 1, 1, 0, 0, LAST)
    assert r["own_kwh"] == pytest.approx(2.0) and r["saving_kr"] == pytest.approx(4.0) and r["income_kr"] == pytest.approx(2.0)


def test_sql_avbrott_i_loggen_raknas_som_hogst_fem_minuter(sl_conn, flat_prices):
    """Två rader med en timmes mellanrum får inte räknas som en timme på samma effekt (3000 W): högst 300 s = 0,25 kWh."""
    _fill(sl_conn, "2026-05-10 12:00+02", 1, pv=3000, net=0, step=3600)
    (raw,) = sp.ew_raw(sl_conn, date(2026, 1, 1), "2026-11")
    assert raw["produced_kwh"] == pytest.approx(3000 * 300 / 3.6e6)


def test_sql_manadsgransen_foljer_installationens_tid_och_importerar_inte_oandliga_varden(sl_conn, flat_prices):
    # 23:30 svensk sommartid 31 maj = 21:30 UTC, ska bli maj; 00:30 svensk tid 1 juni = juni
    _fill(sl_conn, "2026-05-31 23:00+02", 60, pv=1000, net=0)
    _fill(sl_conn, "2026-06-01 00:00:30+02", 60, pv=1000, net=0)
    sl_conn.execute(text("INSERT INTO sensor_log VALUES ('2026-06-02 12:00+02', 1, 'Infinity', 5000)"))
    raws = {r["month"]: r for r in sp.ew_raw(sl_conn, date(2026, 1, 1), "2026-11")}
    assert set(raws) == {"2026-05", "2026-06"}
    assert raws["2026-05"]["produced_kwh"] == pytest.approx(1000 * 3540 / 3.6e6, rel=0.02)
    # juni: 00:00:00 (sista maj-raden i minutserien) + 60 minuter = 3630 s; raden med oändligt värde räknas inte
    assert raws["2026-06"]["produced_kwh"] == pytest.approx(1000 * 3630 / 3.6e6, rel=0.001)


def test_fryst_manad_skrivs_aldrig_over(sl_conn):
    sl_conn.execute(text(sp._SCHEMA))
    sl_conn.execute(text("TRUNCATE solar_payback_months"))
    base = {c: 1.0 for c in sp._FROZEN_COLS if c not in ("month", "scaled")}
    sp.freeze(sl_conn, [{"month": "2026-05", "scaled": False, **base, "benefit_kr": 111.0, "open": False},
                        {"month": "2026-06", "scaled": False, **base, "open": True}])        # pågående: ska inte frysas
    sp.freeze(sl_conn, [{"month": "2026-05", "scaled": False, **base, "benefit_kr": 999.0, "open": False}])
    frozen = sp.load_frozen(sl_conn)
    assert list(frozen) == ["2026-05"] and frozen["2026-05"]["benefit_kr"] == 111.0
    sl_conn.execute(text("TRUNCATE solar_payback_months"))


def test_build_inskrivet_gar_fore_egna_matvarden_och_fryser_inte_inskrivna_manader(sl_conn, flat_prices):
    _fill(sl_conn, "2026-05-01 00:00+02", 31 * 1440 - 1, pv=3000, net=-2000)      # hela maj, en rad per minut
    sl_conn.execute(text(sp._SCHEMA))
    sl_conn.execute(text("TRUNCATE solar_payback_months"))
    st = {"investment_kr": 10000, "start_date": "2026-01-01", "tax_credit_ore": 60, "tax_credit_last_date": LAST,
          "history": [_row("2026-05", 1000, 700)]}
    out = sp.build(sl_conn, st, date(2026, 11, 24))
    (m,) = out["months"]
    assert m["month"] == "2026-05" and m["source"] == "history" and m["produced_kwh"] == 1000     # inskrivet, inte 6 kWh
    assert out["summary"]["total_kr"] == pytest.approx(838.0) and out["history_months"] == 1
    assert sl_conn.execute(text("SELECT count(*) FROM solar_payback_months")).scalar() == 0         # EW-raden för maj frystes inte
    st["history"] = []
    out = sp.build(sl_conn, st, date(2026, 11, 24))
    assert out["months"][0]["source"] == "ew" and out["months"][0]["produced_kwh"] == pytest.approx(3 * 744, rel=0.001)
    assert sl_conn.execute(text("SELECT count(*) FROM solar_payback_months")).scalar() == 1         # nu är den färdig och fryses
    sl_conn.execute(text("TRUNCATE solar_payback_months"))
