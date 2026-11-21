"""capacity_tariff.py - effektavgift efter månadens högsta timmar (#141: Norges kapasitetsledd/effektledd, och svenska
nätbolag som tar betalt efter snittet av 3-5 högsta timmar).

Avgiften bestäms av snittet av månadens N högsta timmar (ofta på N olika dygn) och hamnar i ett trappsteg. Den smarta
gränsen för timmen som pågår är så hög som möjligt utan att snittet går upp ett steg:

    om timmen blir en av de N högsta ersätter den den lägsta av dem (eller dygnets egen topp om samma dygn redan finns)
    nytt snitt = (summa topp-N - den som ersätts + x) / N  <=  stegets övre gräns
    =>  x <= stegets övre gräns × N - (summa topp-N - den som ersätts)

En timme som ändå inte kommer in bland de N högsta (x <= den lägsta av dem) påverkar inte avgiften alls, så gränsen
är aldrig lägre än den. Inställningen (ew_settings "capacity_tariff"): {"enabled", "top_n", "distinct_days", "steps"}.
Ren logik i limit_kw() - testas i tests/test_capacity_tariff.py; main.py använder den som effektvaktens gräns.

Vikt per timme (idé från FTW:s effektkontrakt): vissa nätägare räknar natten (22-06) som en del av effekten, t.ex. hälften.
Timmens värde är då vikt x snittet i kW. Inställningen "night_weight" (0-1, standard 1 = ingen viktning) gäller timmar med
lokal starttid 22-06; weigh() viktar månadens timmar och limit_kw(weight_now=...) räknar om gränsen för timmen som pågår
(en nattimme får gå högre eftersom bara en del av den räknas). Lokal tid, så sommartidsbytet blir rätt.
"""
NIGHT_FROM, NIGHT_TO = 22, 6
# Vanlig norsk trappa (kW) - de flesta nätbolag använder dessa steg; går att ändra i inställningen
DEFAULT_STEPS = [2, 5, 10, 15, 20, 25, 50, 75, 100]


def hour_weight(local_hour, night_weight=1.0):
    """Vikten för en timme med lokal starttid local_hour (0-23): night_weight 22-06, annars 1."""
    try:
        w = float(night_weight)
    except (TypeError, ValueError):
        return 1.0
    if not 0.0 <= w <= 1.0:
        return 1.0
    return w if (local_hour >= NIGHT_FROM or local_hour < NIGHT_TO) else 1.0


def weigh(hours, night_weight=1.0):
    """hours = [(dygn, lokal timme 0-23, kW)] -> [(dygn, vikt x kW)] i samma form som top_hours/limit_kw tar."""
    return [(d, (None if kw is None else kw * hour_weight(h, night_weight))) for d, h, kw in hours]


def top_hours(hour_peaks, top_n=3, distinct_days=True):
    """hour_peaks = [(dygn, kW)] för månadens timmar -> de N högsta [(dygn, kW)], en per dygn om distinct_days."""
    if distinct_days:
        best = {}
        for day, kw in hour_peaks:
            if kw is not None and kw > best.get(day, -1.0):
                best[day] = kw
        items = list(best.items())
    else:
        items = [(d, k) for d, k in hour_peaks if k is not None]
    return sorted(items, key=lambda x: x[1], reverse=True)[:max(1, int(top_n))]


def step_for(avg_kw, steps):
    """(nedre, övre) gräns för trappsteget som snittet ligger i."""
    lo = 0.0
    for s in sorted(float(x) for x in steps):
        if avg_kw <= s:
            return lo, s
        lo = s
    return lo, float("inf")


def limit_kw(hour_peaks, today, top_n=3, distinct_days=True, steps=None, target_kw=None, weight_now=1.0):
    """-> (gräns i kW för timmen som pågår, info). today = dygnet för timmen som pågår. target_kw = trappsteget man siktar
    på (övre gräns, t.ex. 10): gränsen räknas mot det högsta av målsteget och steget man redan hamnat i - annars blir den
    orimligt låg i början av månaden när bara några timmar finns. hour_peaks är redan viktade (weigh()); weight_now är
    vikten för timmen som pågår: bara den delen räknas, så kW-gränsen är den viktade gränsen delad med vikten. Vikt 0 (timmen
    räknas inte alls) ger ingen gräns (inf)."""
    steps = steps or DEFAULT_STEPS
    n = max(1, int(top_n))
    pad = lambda v: (v + [0.0] * n)[:n]
    cur = pad([k for _d, k in top_hours(hour_peaks, n, distinct_days)])
    avg_now = sum(cur) / n
    lo, hi = step_for(avg_now, steps)
    if target_kw:
        hi = max(hi, float(target_kw))
        lo = max([float(x) for x in steps if float(x) < hi] + [0.0])
    # Om timmen som pågår blir en av topparna ersätter den dygnets egen topp (olika dygn) eller den lägsta toppen
    others = pad([k for _d, k in top_hours([(d, k) for d, k in hour_peaks if not (distinct_days and d == today)], n, distinct_days)])
    today_best = max([k for d, k in hour_peaks if d == today] + [0.0]) if distinct_days else 0.0
    base = sorted(others, reverse=True)[:n - 1]                 # de N-1 högsta som står kvar
    free = max(min(others), today_best)                          # under detta påverkas inte snittet alls
    room = hi * n - sum(base) if hi != float("inf") else float("inf")
    limit = max(free, room)
    try:
        wn = float(weight_now)
    except (TypeError, ValueError):
        wn = 1.0
    if not 0.0 <= wn <= 1.0:
        wn = 1.0
    if wn != 1.0:
        limit = limit / wn if wn > 0 else float("inf")
        free = free / wn if wn > 0 else float("inf")
    info = {"avg_kw": round(avg_now, 2), "step": [lo, hi], "top": [round(k, 2) for k in cur],
            "free_below_kw": round(free, 2) if free != float("inf") else None,
            "limit_kw": round(limit, 2) if limit != float("inf") else None, "weight_now": wn}
    return limit, info
