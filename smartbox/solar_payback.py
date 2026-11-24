"""
solar_payback.py - solcellernas nytta och återbetalning, månad för månad, år för år och totalt (#599, #602).

Nyttan per månad är summan av tre delar:

    besparing   = egenanvänd kWh × vad en köpt kWh hade kostat (elpris + påslag + överföring + energiskatt, med moms)
    intäkt      = sålda kWh × (säljpris + nätnytta)
    skattered.  = sålda kWh × skattereduktionen (60 öre/kWh), bara t.o.m. slutdatumet (2025-12-31 i Sverige)

    egenanvänd kWh = producerat - sålt

Fasta avgifter och effektavgift räknas inte: de betalas med eller utan solceller.

Två källor, och en månad med uppgifter inskrivna för hand går alltid före:

  1. Inskrivna månader (``history``). Samma kolumner som mallen (se CSV_COLUMNS), för tiden innan EnergyWizard
     började logga, eller för att rätta en månad efter nätbolagets och elhandlarens fakturor.
  2. EnergyWizards egna mätvärden ur sensor_log (solproduktion och nät, en rad per minut), värderade minut för minut
     med installationens egna elpris- och avgiftsinställningar. Loggen kan ha luckor (omstarter); ``coverage`` är
     andelen av månaden som finns, och summorna skalas upp med den, så att en månad med 8 % lucka inte
     underskattas. Skalningen är märkt i svaret.

Färdiga månader från EnergyWizards egna mätvärden fryses (``solar_payback_months``), så att en senare ändring av
avgifter inte skriver om historiken. Den pågående månaden räknas om varje gång.

Dygn och månader räknas i installationens tidszon. DB-delen ligger sist; resten är rena funktioner (tests/test_solar_payback.py).
"""

import calendar
import csv
import io
import re
from datetime import date

CSV_COLUMNS = ["manad", "producerat_kwh", "salt_kwh", "kopt_kwh", "kopt_pris_ore", "salj_pris_ore",
               "energiskatt_ore", "overforing_ore", "natnytta_ore", "skattereduktion_ore"]
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MAX_HISTORY = 600                      # 50 år
_ALIASES = {"month": "manad", "månad": "manad", "producerat": "producerat_kwh", "såld": "salt_kwh", "sålt_kwh": "salt_kwh",
            "köpt_kwh": "kopt_kwh", "köppris_öre": "kopt_pris_ore", "säljpris_öre": "salj_pris_ore"}


def _num(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "").replace(" ", "").replace("−", "-")
    if not s:
        return default
    s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s
    try:
        return float(s)
    except ValueError:
        return default


def month_end(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, calendar.monthrange(y, m)[1])


def tax_credit_applies(month: str, last_date) -> bool:
    """Skattereduktionen gäller hela månaden om månadens sista dag är före eller på slutdatumet."""
    if not last_date:
        return False
    try:
        return month_end(month) <= date.fromisoformat(str(last_date)[:10])
    except ValueError:
        return False


def compute_month(month, produced, sold, buy_ore, sell_ore, grid_ore, nn_ore, tax_ore, tax_last_date):
    """Nyttan för en månad med uppgifter i kWh och öre per kWh. buy_ore är ALLT en köpt kWh kostar utom nätet
    (elpris + påslag, med moms), grid_ore = överföring + energiskatt (med moms), sell_ore är säljpriset utan moms
    och nn_ore nätnyttan. Skattereduktionen räknas bara fram till slutdatumet."""
    produced, sold = max(0.0, produced), max(0.0, sold)
    own = max(0.0, produced - sold)
    saving = own * (buy_ore + grid_ore) / 100
    income = sold * (sell_ore + nn_ore) / 100
    credit = sold * tax_ore / 100 if tax_credit_applies(month, tax_last_date) else 0.0
    return {"month": month, "produced_kwh": produced, "sold_kwh": sold, "own_kwh": own,
            "saving_kr": saving, "income_kr": income, "tax_credit_kr": credit, "benefit_kr": saving + income + credit}


def from_history_row(row, tax_last_date):
    """En inskriven månad (CSV_COLUMNS) -> månadsraden. Skattereduktionens öre kommer ur raden."""
    r = compute_month(row["manad"], row["producerat_kwh"], row["salt_kwh"], row["kopt_pris_ore"], row["salj_pris_ore"],
                      row["energiskatt_ore"] + row["overforing_ore"], row["natnytta_ore"],
                      row.get("skattereduktion_ore") or 0.0, tax_last_date)
    r["bought_kwh"] = row.get("kopt_kwh")
    r["source"] = "history"
    return r


def parse_history_csv(text_in):
    """CSV-text (semikolon, komma eller tabb; decimalkomma går bra) -> (rader, fel). Rubrikerna avgör kolumnerna,
    så ordningen spelar ingen roll. Ett fel nämner radnumret och vad som är fel; felaktiga rader tas inte med."""
    text_in = (text_in or "").lstrip("﻿")
    lines = [ln for ln in text_in.splitlines() if ln.strip()]
    if not lines:
        return [], ["Filen är tom"]
    head = lines[0]
    delim = max((";", "\t", ","), key=head.count)
    if head.count(delim) == 0:
        return [], ["Hittar inga kolumner. Använd mallens rubriker, åtskilda med semikolon"]
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    header = [_ALIASES.get(h.strip().lower(), h.strip().lower()) for h in next(reader)]
    missing = [c for c in CSV_COLUMNS[:8] if c not in header]
    if missing:
        return [], ["Saknar kolumn: " + ", ".join(missing)]
    rows, errors, seen = [], [], set()
    for n, cells in enumerate(reader, start=2):
        rec = dict(zip(header, cells))
        month = (rec.get("manad") or "").strip()
        if not _MONTH.match(month):
            errors.append(f"Rad {n}: månaden '{month}' ska skrivas ÅÅÅÅ-MM, t.ex. 2026-05")
            continue
        vals, bad = {}, None
        for c in CSV_COLUMNS[1:]:
            v = _num(rec.get(c), 0.0 if c in ("kopt_kwh", "natnytta_ore", "skattereduktion_ore") else None)
            if v is None or v < 0:
                bad = c
                break
            vals[c] = v
        if bad:
            errors.append(f"Rad {n} ({month}): '{bad}' saknas eller är inte ett tal över noll")
            continue
        if vals["salt_kwh"] > vals["producerat_kwh"] * 1.02 + 1:
            errors.append(f"Rad {n} ({month}): sålt ({vals['salt_kwh']:g} kWh) är mer än producerat ({vals['producerat_kwh']:g} kWh)")
            continue
        if month in seen:
            errors.append(f"Rad {n}: månaden {month} finns två gånger, den sista gäller")
        seen.add(month)
        rows = [r for r in rows if r["manad"] != month]
        rows.append({"manad": month, **{k: round(v, 3) for k, v in vals.items()}})
    rows.sort(key=lambda r: r["manad"])
    return rows, errors


def validate_settings(body):
    """Webbens inställningar -> (rensade inställningar, fel). Bara kända fält; allt annat kastas."""
    errors, out = [], {}
    inv = _num(body.get("investment_kr"))
    if inv is None or inv <= 0 or inv > 5_000_000:
        errors.append("Anläggningens kostnad ska vara ett belopp över noll")
    else:
        out["investment_kr"] = round(inv, 2)
    sd = str(body.get("start_date") or "")[:10]
    try:
        date.fromisoformat(sd)
        out["start_date"] = sd
    except ValueError:
        errors.append("Startdatum ska skrivas ÅÅÅÅ-MM-DD")
    tax = _num(body.get("tax_credit_ore"), 0.0)
    if tax is None or tax < 0 or tax > 500:
        errors.append("Skattereduktionen ska vara 0 till 500 öre per kWh")
    else:
        out["tax_credit_ore"] = round(tax, 2)
    nn = _num(body.get("natnytta_ore"), 0.0)
    if nn is None or nn < 0 or nn > 100:
        errors.append("Nätnyttan ska vara 0 till 100 öre per kWh")
    else:
        out["natnytta_ore"] = round(nn, 2)
    last = str(body.get("tax_credit_last_date") or "")[:10]
    if last:
        try:
            date.fromisoformat(last)
            out["tax_credit_last_date"] = last
        except ValueError:
            errors.append("Skattereduktionens slutdatum ska skrivas ÅÅÅÅ-MM-DD")
    else:
        out["tax_credit_last_date"] = ""
    return out, errors


def summarize(months, investment_kr):
    """Månadsrader (sorterade) -> årssummor, ackumulerat och återbetalning.

    Tid kvar räknas på nyttan de senaste 12 hela månaderna i listan (``last12_kr``), inte på snittet sedan start, så att
    t.ex. borttagen skattereduktion slår igenom. None när det inte finns ett helt år ännu."""
    months = sorted(months, key=lambda r: r["month"])
    acc, years, series = 0.0, {}, []
    for r in months:
        acc += r["benefit_kr"]
        y = years.setdefault(r["month"][:4], {"year": r["month"][:4], "months": 0, "produced_kwh": 0.0, "sold_kwh": 0.0,
                                              "own_kwh": 0.0, "saving_kr": 0.0, "income_kr": 0.0, "tax_credit_kr": 0.0,
                                              "benefit_kr": 0.0})
        y["months"] += 1
        for k in ("produced_kwh", "sold_kwh", "own_kwh", "saving_kr", "income_kr", "tax_credit_kr", "benefit_kr"):
            y[k] += r[k]
        series.append({"month": r["month"], "benefit_kr": round(r["benefit_kr"], 2), "cumulative_kr": round(acc, 2)})
    for y in years.values():
        y["own_pct"] = round(100 * y["own_kwh"] / y["produced_kwh"], 1) if y["produced_kwh"] else None
        for k in list(y):
            if isinstance(y[k], float):
                y[k] = round(y[k], 2)
    last12 = sum(r["benefit_kr"] for r in months[-12:]) if len(months) >= 12 else None
    inv = float(investment_kr or 0)
    left = max(0.0, inv - acc) if inv else None
    return {"total_kr": round(acc, 2), "investment_kr": inv or None, "paid_back_pct": round(100 * acc / inv, 1) if inv else None,
            "remaining_kr": round(left, 2) if left is not None else None, "last12_kr": round(last12, 2) if last12 is not None else None,
            "years_left": round(left / last12, 1) if (left is not None and last12 and last12 > 0) else None,
            "years": list(years.values()), "series": series, "months": len(months)}


# ---- EnergyWizards egna mätvärden (sensor_log) --------------------------------------------------------------------
# Varje rads effekt gäller tills nästa rad, högst 5 minuter (som energy_history.py): ett avbrott i loggningen räknas inte
# som timmar på samma effekt. Svaret per månad är råvärden: producerat, sålt, köpt och två viktade priser. Själva nyttan
# räknas i estimate(), så att kalibreringen kan korrigera kWh innan det värderas.
#
# Priserna viktas med egenanvänd effekt per minut (produktion minus export, aldrig under noll) respektive med exporten,
# så att en kWh solel som används klockan 12 värderas med priset klockan 12 och inte med månadens snitt.
_EW_SQL = """
WITH r AS (
  SELECT timestamp, price, net_power::float8 AS n, pv_power_w::float8 AS pv,
         CASE WHEN LEAD(timestamp) OVER (ORDER BY timestamp) IS NULL THEN 0   -- LEAST ignorerar NULL: sista raden fick annars 300 s
              ELSE LEAST(EXTRACT(EPOCH FROM (LEAD(timestamp) OVER (ORDER BY timestamp) - timestamp)), 300) END AS dt
  FROM sensor_log
  WHERE net_power IS NOT NULL AND pv_power_w IS NOT NULL AND price IS NOT NULL
    AND net_power::float8 NOT IN ('Infinity','-Infinity','NaN') AND pv_power_w::float8 NOT IN ('Infinity','-Infinity','NaN')
    AND timestamp >= :since)
SELECT to_char(timestamp AT TIME ZONE __EW_TIMEZONE__, 'YYYY-MM') AS month,
       sum(GREATEST(pv, 0) * dt) / 3.6e6 AS produced_kwh,
       sum(GREATEST(-n, 0) * dt) / 3.6e6 AS sold_kwh,
       sum(GREATEST(n, 0) * dt) / 3.6e6 AS bought_kwh,
       sum(GREATEST(GREATEST(pv, 0) - GREATEST(-n, 0), 0) * dt) / 3.6e6 AS own_pos_kwh,
       sum(GREATEST(GREATEST(pv, 0) - GREATEST(-n, 0), 0) * dt * {buy}) / 3.6e6 AS own_pos_value,
       sum(GREATEST(-n, 0) * dt * {sell}) / 3.6e6 AS sold_value,
       sum(dt) AS seconds
FROM r WHERE dt IS NOT NULL
GROUP BY 1 ORDER BY 1"""

MIN_COVERAGE = 0.5          # under det tas en månad inte med (för lite att gå på)
CAL_MIN_MONTHS = 3          # så många månader med både egna mätvärden och inskrivna krävs för att kalibrera
CAL_MIN_COVERAGE = 0.9      # och bara månader med nästan hela loggen räknas in i kalibreringen
CAL_RANGE = (0.8, 1.25)     # en faktor utanför detta är ett fel i data, inte en kalibrering


def _ew_query():
    import nordpool
    from local_sql import local_sql
    from sqlalchemy import text
    buy = nordpool.sql_buy_cost_expr("price", "timestamp")
    sell = nordpool.sql_sell_income_expr("price")
    return text(local_sql(_EW_SQL.format(buy=buy, sell=sell)))


def month_seconds(month: str) -> float:
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1] * 86400.0


def ew_raw(conn, since, today_month):
    """Råvärden per månad ur sensor_log från ``since`` (datum). Priser i kr/kWh (databasens valuta)."""
    out = []
    for month, prod, sold, bought, own_pos, own_val, sold_val, seconds in conn.execute(_ew_query(), {"since": since}).fetchall():
        prod, sold, bought, own_pos, own_val, sold_val, seconds = (float(x or 0) for x in (prod, sold, bought, own_pos, own_val, sold_val, seconds))
        cov = min(1.0, seconds / month_seconds(month))
        out.append({"month": month, "produced_kwh": prod, "sold_kwh": sold, "bought_kwh": bought, "coverage": cov,
                    "buy_kr_kwh": own_val / own_pos if own_pos > 0 else 0.0, "sell_kr_kwh": sold_val / sold if sold > 0 else 0.0,
                    "open": month >= today_month})
    return out


def _full(raw):
    """Råvärden uppskalade för luckor i loggen (1/coverage). Pågående månad skalas inte, den är inte slut."""
    k = 1.0 if raw["open"] or raw["coverage"] >= 0.999 else 1.0 / raw["coverage"]
    return raw["produced_kwh"] * k, raw["sold_kwh"] * k, raw["bought_kwh"] * k, k


def calibrate(raws, history_rows):
    """Faktorer (produktion, såld, antal månader) som får EnergyWizards mätvärden att stämma med inskrivna månader.

    Solens och nätets mätare läses inte exakt som växelriktarens och nätägarens (några procent åt vardera håll), och
    egenanvänd el är skillnaden mellan de två: 3 % fel på vardera ger 20 % fel på egenanvänd el en sommarmånad.
    Faktorerna är summan inskrivet delat med summan uppmätt över månader som finns i båda. Färre än CAL_MIN_MONTHS
    månader, eller en faktor utanför CAL_RANGE, ger (1, 1, n) - då korrigeras ingenting."""
    hist = {h["month"]: h for h in history_rows}
    hp = rp = hs = rs = 0.0
    n = 0
    for r in raws:
        h = hist.get(r["month"])
        if not h or r["open"] or r["coverage"] < CAL_MIN_COVERAGE or h["produced_kwh"] <= 0:
            continue
        p, s_, _b, _k = _full(r)
        hp, rp, hs, rs, n = hp + h["produced_kwh"], rp + p, hs + h["sold_kwh"], rs + s_, n + 1
    if n < CAL_MIN_MONTHS or rp <= 0 or rs <= 0:
        return 1.0, 1.0, n
    kp, ks = hp / rp, hs / rs
    lo, hi = CAL_RANGE
    return (kp, ks, n) if lo <= kp <= hi and lo <= ks <= hi else (1.0, 1.0, n)


def estimate(raw, kp, ks, nn_ore, tax_ore, tax_last_date):
    """Månadsraden ur råvärden. Egenanvänd el = (kalibrerat) producerat - sålt, värderad med de viktade priserna."""
    p, s_, b, k = _full(raw)
    p, s_ = p * kp, s_ * ks
    own = max(0.0, p - s_)
    saving = own * raw["buy_kr_kwh"]
    income = s_ * (raw["sell_kr_kwh"] + nn_ore / 100)
    credit = s_ * tax_ore / 100 if tax_credit_applies(raw["month"], tax_last_date) else 0.0
    return {"month": raw["month"], "produced_kwh": p, "sold_kwh": s_, "bought_kwh": b, "own_kwh": own,
            "saving_kr": saving, "income_kr": income, "tax_credit_kr": credit, "benefit_kr": saving + income + credit,
            "source": "ew", "coverage": round(raw["coverage"], 3), "scaled": k > 1.0, "open": raw["open"],
            "calibrated": (kp, ks) != (1.0, 1.0)}


def ew_months(conn, since, today_month, tax_ore, tax_last_date, nn_ore=0.0, history_rows=()):
    """Månadsrader ur sensor_log (kalibrerade mot ``history_rows``) och kalibreringen: (rader, (kp, ks, n))."""
    raws = ew_raw(conn, since, today_month)
    kp, ks, n = calibrate(raws, history_rows)
    rows = [estimate(r, kp, ks, nn_ore, tax_ore, tax_last_date) for r in raws if r["open"] or r["coverage"] >= MIN_COVERAGE]
    return rows, (kp, ks, n)


_SCHEMA = """CREATE TABLE IF NOT EXISTS solar_payback_months (
    month TEXT PRIMARY KEY, produced_kwh DOUBLE PRECISION, sold_kwh DOUBLE PRECISION, bought_kwh DOUBLE PRECISION,
    own_kwh DOUBLE PRECISION, saving_kr DOUBLE PRECISION, income_kr DOUBLE PRECISION, tax_credit_kr DOUBLE PRECISION,
    benefit_kr DOUBLE PRECISION, coverage DOUBLE PRECISION, scaled BOOLEAN, computed_at TIMESTAMPTZ DEFAULT now())"""
_FROZEN_COLS = ("month", "produced_kwh", "sold_kwh", "bought_kwh", "own_kwh", "saving_kr", "income_kr", "tax_credit_kr",
                "benefit_kr", "coverage", "scaled")


def load_frozen(conn):
    from sqlalchemy import text
    conn.execute(text(_SCHEMA))
    rows = conn.execute(text(f"SELECT {', '.join(_FROZEN_COLS)} FROM solar_payback_months ORDER BY month")).fetchall()
    out = {}
    for r in rows:
        d = dict(zip(_FROZEN_COLS, r))
        out[d["month"]] = {**{k: (float(v) if isinstance(v, (int, float)) or hasattr(v, "quantize") else v)
                              for k, v in d.items() if k not in ("month", "scaled")},
                           "month": d["month"], "scaled": bool(d["scaled"]), "source": "ew", "open": False}
    return out


def freeze(conn, rows):
    """Sparar färdiga månader (ej den pågående). ON CONFLICT DO NOTHING: en fryst månad skrivs aldrig över."""
    from sqlalchemy import text
    for r in rows:
        if r.get("open"):
            continue
        conn.execute(text(f"INSERT INTO solar_payback_months ({', '.join(_FROZEN_COLS)}) VALUES "
                          f"({', '.join(':' + c for c in _FROZEN_COLS)}) ON CONFLICT (month) DO NOTHING"),
                     {c: r.get(c) for c in _FROZEN_COLS})


def build(conn, settings, today, freeze_months=True):
    """Hela svaret: månadsrader (inskrivna före egna mätvärden), sammanfattning och inställningar.

    settings = ew_settings 'solar_payback'. today = dagens datum i installationens tidszon (date)."""
    st = settings or {}
    tax_ore = _num(st.get("tax_credit_ore"), 0.0) or 0.0
    last = st.get("tax_credit_last_date") or ""
    history = {}
    for row in st.get("history") or []:
        try:
            history[row["manad"]] = from_history_row(row, last)
        except (KeyError, TypeError, ValueError):
            continue
    start = str(st.get("start_date") or "")[:10]
    today_month = today.strftime("%Y-%m")
    since = date.fromisoformat(start) if start else date(today.year - 5, 1, 1)
    frozen = load_frozen(conn)
    hist_rows = [r for r in (st.get("history") or []) if isinstance(r, dict) and "manad" in r]
    hist_cmp = [{"month": r["manad"], "produced_kwh": r.get("producerat_kwh", 0), "sold_kwh": r.get("salt_kwh", 0)} for r in hist_rows]
    live, cal = ew_months(conn, since, today_month, tax_ore, last, _num(st.get("natnytta_ore"), 0.0) or 0.0, hist_cmp)
    if freeze_months:
        freeze(conn, [r for r in live if r["month"] not in history])
    merged = {}
    for r in live:
        merged[r["month"]] = frozen.get(r["month"], r) if not r.get("open") else r
    for m, r in frozen.items():
        merged.setdefault(m, r)
    merged.update(history)                                    # inskrivet går före
    months = [r for m, r in sorted(merged.items()) if not start or m >= start[:7]]
    # Den pågående månaden räknas inte in i tid kvar och procent; den visas men markeras
    closed = [r for r in months if not r.get("open")]
    summary = summarize(closed, st.get("investment_kr"))
    return {"months": months, "summary": summary, "tax_credit_ore": tax_ore, "tax_credit_last_date": last,
            "calibration": {"months": cal[2], "produced_factor": round(cal[0], 4), "sold_factor": round(cal[1], 4),
                            "active": (cal[0], cal[1]) != (1.0, 1.0)},
            "investment_kr": st.get("investment_kr"), "start_date": start, "history_months": len(history),
            "natnytta_ore": _num(st.get("natnytta_ore"), 0.0) or 0.0}
