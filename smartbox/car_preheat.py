"""car_preheat.py - hur många minuter i förväg bilens värme ska starta, lärt ur bilens egna värmepass (#598).

Förut: fast modell ur utetemperaturen (30 min vid 0 °C, +0,75 min per grad kallare). Men tiden beror på hur kall bilen är när
värmen startar, och olika bilar värmer olika snabbt. Nu: ur sensor_log hämtas varje bils tidigare värmepass (klimatläget går
från av till på och kupétemperaturen stiger mätbart), och tiden per grad till måltemperaturen läggs ihop (median). Förväntad
tid = minuter per grad * (mål - starttemperatur) + marginal. Saknas tillräckligt med pass, eller bilens kupétemperatur inte
går att lita på (Tesla via HA visar ofta en gammal temperatur som hoppar rakt till målet), faller det tillbaka på den gamla
modellen. Starttemperaturen är bilens kupétemperatur, men aldrig mer än UTE_MARGIN grader över utetemperaturen: en bil som
stått länge är ungefär lika kall som luften ute, och en gammal avläsning ska inte få värmen att starta för sent.
"""
import statistics
import time

UTE_MARGIN = 5.0
MARGIN_MIN = 3.0            # extra minuter så att den är varm, inte bara på väg
MIN_MIN, MAX_MIN = 10.0, 90.0
MIN_SESSIONS = 3
MIN_DELTA = 4.0             # ett pass måste höja temperaturen minst så här mycket för att räknas
MIN_STEPS = 4               # och visa minst så här många olika avläsningar (annars är temperaturen gammal och hoppar)
_OFF = ("off", "unknown", "unavailable", "none", "", None)
_cache = {}
CACHE_S = 6 * 3600


def old_model(outdoor):
    """Den gamla modellen (learning.estimate_preheat_minutes): 30 min vid 0 °C, kallare = längre, 15-60 min."""
    o = 10.0 if outdoor is None else outdoor
    return max(15.0, min(60.0, 30 + (0 - o) * 0.75))


def sessions(rows):
    """rows: [(tid_s, läge, kupétemp)] i tidsordning. Ett pass = sammanhängande rader där klimatläget inte är av.
    Returnerar [(start_temp, högsta_temp, minuter_till_högsta, antal_olika_avläsningar)] för pass med giltiga temperaturer."""
    out, cur = [], []
    for ts, st, t in rows:
        on = str(st).lower() not in _OFF
        if on and t is not None:
            cur.append((ts, float(t)))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    res = []
    for s in out:
        t0 = s[0][1]
        peak = max(t for _, t in s)
        # minuter till första avläsningen som nått 0,5 °C under toppen (toppen = vad bilen kom upp i)
        reach = next(ts for ts, t in s if t >= peak - 0.5)
        steps = len({t for _, t in s})
        res.append((t0, peak, (reach - s[0][0]) / 60.0, steps))
    return res


def minutes_per_degree(sess, target):
    """Median av minuter per grad över giltiga pass: kom upp minst MIN_DELTA grader, minst MIN_STEPS avläsningar, och
    toppen låg nära (inom 3 °C under) eller över måltemperaturen så att passet visar tiden hela vägen."""
    vals = []
    for t0, peak, minutes, steps in sess:
        d = peak - t0
        if d >= MIN_DELTA and steps >= MIN_STEPS and 1 < minutes <= MAX_MIN and peak >= target - 3.0:
            vals.append(minutes / d)
    if len(vals) < MIN_SESSIONS:
        return None
    return statistics.median(vals)


def predict(mpd, start_temp, target, outdoor):
    """Minuter i förväg. start_temp kan vara None (okänd): då antas utetemperaturen."""
    o = 10.0 if outdoor is None else outdoor
    t0 = o if start_temp is None else min(float(start_temp), o + UTE_MARGIN)
    if mpd is None:
        return old_model(outdoor)
    need = max(0.0, target - t0)
    return max(MIN_MIN, min(MAX_MIN, mpd * need + MARGIN_MIN))


def load_rows(get_db, car_id, days=90):
    """Bilens klimatrader ur sensor_log (kolumnerna {bil}_climate_state och {bil}_climate_temp). get_db = logger.get_db
    (psycopg). Tom lista om kolumnerna saknas."""
    if not car_id.replace("_", "").isalnum():
        return []
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT extract(epoch FROM timestamp), "{car_id}_climate_state", "{car_id}_climate_temp" '
                            f"FROM sensor_log WHERE timestamp > now() - make_interval(days => %s) "
                            f'AND "{car_id}_climate_state" IS NOT NULL ORDER BY timestamp', (days,))
                r = cur.fetchall()
        return [(float(a), b, None if t is None else float(t)) for a, b, t in r]
    except Exception:
        return []


def minutes(get_db, car_id, outdoor, start_temp, target, now_s=None):
    """(minuter, förklaring). Lärd modell per bil, cachad i sex timmar."""
    now_s = time.time() if now_s is None else now_s
    key = (car_id, round(target, 1))
    hit = _cache.get(key)
    if not hit or now_s - hit[0] > CACHE_S:
        mpd = minutes_per_degree(sessions(load_rows(get_db, car_id)), target)
        hit = _cache[key] = (now_s, mpd)
    mpd = hit[1]
    m = predict(mpd, start_temp, target, outdoor)
    why = (f"lärt: {mpd:.1f} min per grad" if mpd is not None else "grundmodell (för få mätta värmepass)")
    return m, why
