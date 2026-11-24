"""Prövar EnergyWizards egna mätvärden mot facit för solcellernas återbetalning (smartbox/solar_payback.py).

Facit är en CSV med mallens kolumner (samma fil som läses in under Solceller > Återbetalning) för månader där
EnergyWizard också har loggat. Skriptet kalibrerar på månaderna före varje prövad månad ("framåt", så att facit för
månaden själv aldrig används) och skriver ut felet för producerat, sålt, egenanvänt och nytta, med och utan kalibrering.

    POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... POSTGRES_HOST=... \\
        python scripts/backtest_solar_payback.py facit.csv [--from 2026-06] [--tax-until 2025-12-31]

Läser bara (SELECT). Priserna värderas med installationens egna inställningar, så ett fel i dem syns här som fel i nyttan.
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
import solar_payback as sp  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("facit")
    ap.add_argument("--from", dest="first", default="2026-01")
    ap.add_argument("--tax-until", default="")
    a = ap.parse_args()
    from sqlalchemy import create_engine
    e = create_engine(f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@"
                      f"{os.environ.get('POSTGRES_HOST', 'postgres-smartbox')}/{os.environ['POSTGRES_DB']}")
    rows, errors = sp.parse_history_csv(open(a.facit, encoding="utf-8").read())
    for er in errors:
        print("facit:", er)
    truth = {r["manad"]: sp.from_history_row(r, a.tax_until) for r in rows}
    hist = {r["manad"]: r for r in rows}
    today_month = date.today().strftime("%Y-%m")
    with e.connect() as c:
        raws = sp.ew_raw(c, date.fromisoformat(a.first + "-01"), today_month)
    byrm = {r["month"]: r for r in raws}
    print("mån       kalibrering          producerat      sålt         egenanvänt      nytta (utan skattereduktion)   okalibrerad")
    sums = [0.0, 0.0, 0.0]
    for m in sorted(byrm):
        t = truth.get(m)
        r = byrm[m]
        if not t or r["open"] or r["coverage"] < sp.MIN_COVERAGE:
            continue
        past = [{"month": k, "produced_kwh": h["producerat_kwh"], "sold_kwh": h["salt_kwh"]} for k, h in hist.items() if k < m]
        kp, ks, n = sp.calibrate(raws, past)
        est, raw = sp.estimate(r, kp, ks, 0.0, 0.0, ""), sp.estimate(r, 1.0, 1.0, 0.0, 0.0, "")
        want = t["saving_kr"] + t["income_kr"] - hist[m]["natnytta_ore"] * t["sold_kwh"] / 100
        pct = lambda x, y: f"{100 * (x / y - 1):+5.0f} %" if y else "    – "
        print(f"{m}  {kp:.3f}/{ks:.3f} n={n}  {est['produced_kwh']:7.0f}/{t['produced_kwh']:<6.0f} {est['sold_kwh']:6.0f}/{t['sold_kwh']:<6.0f}"
              f" {est['own_kwh']:5.0f}/{t['own_kwh']:<5.0f}  {est['saving_kr'] + est['income_kr']:6.0f}/{want:<6.0f} {pct(est['saving_kr'] + est['income_kr'], want)}"
              f"   {pct(raw['saving_kr'] + raw['income_kr'], want)}")
        if n >= sp.CAL_MIN_MONTHS:
            sums[0] += est["saving_kr"] + est["income_kr"]
            sums[1] += raw["saving_kr"] + raw["income_kr"]
            sums[2] += want
    if sums[2]:
        print(f"\nKalibrerade månader: {sums[0]:.0f} kr mot facit {sums[2]:.0f} kr ({100 * (sums[0] / sums[2] - 1):+.1f} %); utan kalibrering {sums[1]:.0f} kr ({100 * (sums[1] / sums[2] - 1):+.1f} %)")


if __name__ == "__main__":
    main()
