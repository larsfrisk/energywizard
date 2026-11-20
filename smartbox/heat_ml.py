"""ML-valt börvärde för rumsåterkopplingen (Emil 2026-11-15: "Det ska du veta med ML").

Modell (lärs ur husets egen logg, sensor_log, senaste 45 dygnen, kvartsvärden):
    förändring av innetemperaturen per timme = w0 + w1 * börvärde (snitt över perioden)
                                                  + w2 * börvärde (snitt 2 h före; golvvärmens eftersläpning)
                                                  + w3 * (inne - ute)
skattad med minsta kvadrat över 4-timmarsperioder (utan soltimmar). Hos Emil: ca +0,02 °C/h per grad börvärde och
-0,10 °C/h vid börvärde 15 och 2 °C ute. Mätvärdena hoppar i tiondelar, så förklaringsgraden är låg men koefficienterna
stabila; därför en säkerhetsmarginal och en löpande nivårättning (bias) mot hur det faktiskt gick de senaste timmarna.

Val (choose):
  - dyrt: LÄGSTA börvärde där de två kallaste rummen (snitt) förutsägs ligga kvar över golvet + marginal fram till nästa
    billiga period (högst 8 h fram). Ligger rummen redan över golvet höjs börvärdet inte över sparläget: en prognos som
    vill ha 23 °C när rummen är 21 °C startar kompressorn och köper el nu, fast valet görs om varje minut (#517).
  - billigt: HÖGSTA börvärde där huset (median) förutsägs ligga under maxgränsen - marginal till slutet av den billiga
    perioden (högst 6 h)
  - inom de hårda gränserna (heat_feedback_min_sp/max_sp, standard 15-25)
Finns för lite data (färre än MIN_SAMPLES perioder) returneras None och den enkla regeln i gpm gäller.
"""
from datetime import datetime, timedelta

HORIZON_H = 4
MIN_SAMPLES = 400
MARGIN_LOW = 0.2         # °C över golvet som de kallaste rummen ska hålla
MARGIN_HIGH = 0.3        # °C under maxgränsen
ABOVE_FLOOR = 0.4        # samma band som gpm: under det tar golvvakten över, inte den här spärren
MAX_EXPENSIVE_H = 8.0
MAX_CHEAP_H = 6.0
REFIT = timedelta(hours=24)

_model = {"w": None, "n": 0, "at": None, "bias": 0.0}


def fit(rows):
    """rows: [(tid, inne, börvärde, ute, sol_w)] per kvart i tidsordning. Returnerar (w, n) eller (None, n)."""
    import numpy as np
    step = timedelta(minutes=15)
    X, y = [], []
    k = HORIZON_H * 4
    for i in range(8, len(rows) - k):
        seg = rows[i:i + k + 1]
        if seg[-1][0] - seg[0][0] != step * k:
            continue
        if any(r[1] is None or r[2] is None or r[3] is None for r in seg) or max((r[4] or 0) for r in seg) > 300:
            continue
        prev = [r[2] for r in rows[i - 8:i] if r[2] is not None]
        if len(prev) < 6:
            continue
        sp = sum(r[2] for r in seg[:-1]) / k
        tout = sum(r[3] for r in seg[:-1]) / k
        X.append([1.0, sp, sum(prev) / len(prev), seg[0][1] - tout])
        y.append((seg[-1][1] - seg[0][1]) / HORIZON_H)
    if len(y) < MIN_SAMPLES:
        return None, len(y)
    w, *_ = np.linalg.lstsq(np.array(X), np.array(y), rcond=None)
    if not (w[1] + w[2]) > 0:          # fysikkontroll: högre börvärde måste ge varmare hus
        return None, len(y)
    return [float(v) for v in w], len(y)


def rate(w, sp, sp_prev, tin, tout, bias=0.0):
    return w[0] + w[1] * sp + w[2] * sp_prev + w[3] * (tin - tout) + bias


def predict_end(w, start, sp, tin_median, tout, hours, bias=0.0):
    """Temperatur efter `hours` timmar med börvärdet sp hela tiden (golvvärmens eftersläpning: första 2 h räknas med
    det gamla börvärdet i lagtermen - förenklat till sp, eftersom valet görs om var 15:e minut)."""
    t, tm = start, tin_median
    steps = max(1, int(round(hours * 4)))
    for _ in range(steps):
        r = rate(w, sp, sp, tm, tout, bias) / 4.0
        t += r
        tm += r
    return t


def choose(w, mode, low2, median, tout, hours, floor, indoor_max, lo, hi, bias=0.0):
    """(börvärde, förklaring) eller (None, förklaring) om inget börvärde klarar villkoret."""
    cands = [lo + 0.5 * i for i in range(int(round((hi - lo) / 0.5)) + 1)]
    if mode == "EXPENSIVE":
        h = min(max(hours, 0.25), MAX_EXPENSIVE_H)
        # Rummen är redan över golvet. Prognosen räknas om varje minut, så ett högt börvärde nu
        # värmer huset på dyr el i stället för att vänta tills rummen närmar sig golvet (#517).
        cap = min(max(float(floor), float(lo)), float(hi)) if low2 >= floor + ABOVE_FLOOR else None
        pool = [sp for sp in cands if cap is None or sp <= cap]
        for sp in pool:                                    # lägsta som håller golvet
            end = predict_end(w, low2, sp, median, tout, h, bias)
            if end >= floor + MARGIN_LOW:
                return sp, f"ML: lägsta börvärde som håller de två kallaste rummen över {floor + MARGIN_LOW:.1f} °C i {h:.1f} h (förutsägs {end:.1f} °C)"
        if cap is not None:
            return cap, "ML: rummen ligger över golvet, börvärdet höjs inte under dyr el"
        return None, f"ML: inget börvärde håller golvet i {h:.1f} h"
    h = min(max(hours, 0.25), MAX_CHEAP_H)
    best = None
    for sp in cands:                                       # högsta som inte går över taket
        end = predict_end(w, median, sp, median, tout, h, bias)
        if end <= indoor_max - MARGIN_HIGH:
            best = (sp, end)
    if best:
        return best[0], f"ML: högsta börvärde som håller huset under {indoor_max - MARGIN_HIGH:.1f} °C i {h:.1f} h (förutsägs {best[1]:.1f} °C)"
    return None, f"ML: alla börvärden förutsägs ta huset över {indoor_max - MARGIN_HIGH:.1f} °C"


def model(now=None):
    """Den inlärda modellen (w) eller None. Lärs om en gång per dygn."""
    now = now or datetime.now()
    if _model["at"] is not None and now - _model["at"] < REFIT:
        return _model["w"]
    _model["at"] = now
    try:
        import logger
        with logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '60s'")
            cur.execute("""
                SELECT date_trunc('hour', timestamp) + floor(extract(minute from timestamp)/15) * interval '15 min' AS q,
                       avg(nullif(indoor_temp, 20)), avg(room_temp_setpoint), avg(outdoor_temp), avg(pv_power_w)
                FROM sensor_log WHERE timestamp > now() - interval '45 days' GROUP BY 1 ORDER BY 1""")
            rows = [(r[0], *(None if v is None else float(v) for v in r[1:])) for r in cur.fetchall()]
        w, n = fit(rows)
        _model.update(w=w, n=n)
        print(f"🧠 Börvärdesmodell (ML): {'lärd på ' + str(n) + ' perioder' if w else 'för lite data (' + str(n) + ' perioder)'}.")
    except Exception as e:
        print(f"⚠️ Börvärdesmodellen (ML) kunde inte läras: {type(e).__name__}")
        _model.update(w=None)
    return _model["w"]


def horizon(now, dyn_limit, hysteresis=0.0):
    """(timmar till nästa billiga kvart, timmar billigt kvar från nu) ur pristabellen, 12 h fram."""
    try:
        import logger
        import nordpool
        with logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= %s AND time_start < %s ORDER BY time_start",
                        (now - timedelta(minutes=15), now + timedelta(hours=12)))
            rows = [(t, float(p)) for t, p in cur.fetchall() if p is not None]
    except Exception:
        return None, None
    if not rows:
        return None, None
    c = nordpool.cost_settings()
    cheap = [(t, nordpool.planning_buy_price(p, t, c) <= dyn_limit) for t, p in rows]
    to_cheap = next(((t - now).total_seconds() / 3600 for t, ch in cheap if ch and t >= now - timedelta(minutes=15)), 12.0)
    left = 0.0
    for t, ch in cheap:
        if t < now - timedelta(minutes=15):
            continue
        if not ch:
            break
        left += 0.25
    return max(0.0, to_cheap), left


class Bias:
    """Löpande nivårättning: förutsagd mot verklig förändring de senaste 2 timmarna (dämpad)."""
    def __init__(self):
        self.hist = []      # (tid, inne, förutsagd takt)
        self.value = 0.0

    def update(self, now, tin, predicted_rate):
        if tin is None or predicted_rate is None:
            return self.value
        self.hist = [h for h in self.hist if now - h[0] <= timedelta(hours=2, minutes=5)] + [(now, tin, predicted_rate)]
        old = self.hist[0]
        dt_h = (now - old[0]).total_seconds() / 3600
        if dt_h >= 1.5:
            actual = (tin - old[1]) / dt_h
            pred = sum(h[2] for h in self.hist) / len(self.hist)
            err = actual - pred
            self.value = max(-0.1, min(0.1, 0.7 * self.value + 0.3 * err))
        return self.value
