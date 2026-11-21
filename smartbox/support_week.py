"""support_week.py - veckan som ett par rader i supportutdraget (#227).

En felrapport får inte bara de senaste två timmarna utan också en rad per dygn de senaste sju: vad huset köpte och sålde,
solen, bilen, batteriets lägsta och högsta laddning (dag och natt), hur ofta batteriplanen byttes, hur länge värmepumpen
gick, hål i minutdatan (omstarter och avbrott) och hur många fel och varningar som loggats, plus de vanligaste felen.
Idén är från FTW 0.164 ("What happened over the last week"). Bara siffror, antal och sanerade felrader: inga namn,
entity-id, adresser eller koordinater. Ren logik i summarize() - testas i tests/test_support_week.py.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta

DAYS = 7
NIGHT_FROM, NIGHT_TO = 22, 6           # lokal tid: natt = 22-06
GAP_MIN = 3                            # ett glapp över så här många minuter räknas som ett hål i datan
CAP_MIN = 5                            # ett prov gäller högst så länge när energin räknas (minutdata)
TOP_ERRORS = 3


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _ev_kw(v) -> float:
    """Bilens effekt i kW. Vissa äldre rader loggade W (som live_flow.nodes)."""
    x = _f(v)
    if x is None or x <= 0:
        return 0.0
    return x / 1000.0 if x > 100 else x


def _night(local: datetime) -> bool:
    return local.hour >= NIGHT_FROM or local.hour < NIGHT_TO


def summarize(rows, journal, tz, now: datetime, days: int = DAYS, scrub=lambda s: s) -> list[str]:
    """rows: (ts, net_power W, pv_power_w, battery_soc %, ev_power_kw, ev_carport_power_kw, compressor_running,
    battery_plan_id), äldst först. journal: (ts, lvl, msg) med nivåerna 'fel' och 'varning'. Returnerar utdragsraderna."""
    now_local = now.astimezone(tz)
    today = now_local.date()
    first = today - timedelta(days=days - 1)
    rows = [r for r in rows if r[0] is not None]
    acc: dict = {}
    prev_plan = None
    for i, r in enumerate(rows):
        ts, net, pv, soc, ev1, ev2, comp, plan = r
        local = ts.astimezone(tz)
        d = local.date()
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        dt = (nxt - ts) if nxt is not None else timedelta(minutes=1)
        if dt.total_seconds() < 0:
            dt = timedelta(minutes=1)
        h = min(dt, timedelta(minutes=CAP_MIN)).total_seconds() / 3600.0
        if d < first or d > today:
            prev_plan = plan if plan is not None else prev_plan
            continue
        a = acc.setdefault(d, {"n": 0, "buy": 0.0, "sell": 0.0, "pv": 0.0, "ev": 0.0, "comp": 0.0, "soc": [], "nsoc": [],
                               "plans": 0, "gaps": 0, "gap_min": 0.0, "fel": 0, "varn": 0})
        a["n"] += 1
        n = _f(net)
        if n is not None:
            a["buy" if n > 0 else "sell"] += abs(n) / 1000.0 * h
        p = _f(pv)
        if p is not None and p > 0:
            a["pv"] += p / 1000.0 * h
        a["ev"] += (_ev_kw(ev1) + _ev_kw(ev2)) * h
        c = _f(comp)
        if c is not None and c > 0:
            a["comp"] += h * 60.0
        s = _f(soc)
        if s is not None:
            a["soc"].append(s)
            if _night(local):
                a["nsoc"].append(s)
        if plan is not None:
            if prev_plan is not None and plan != prev_plan:
                a["plans"] += 1
            prev_plan = plan
        if dt > timedelta(minutes=GAP_MIN) and nxt is not None:
            a["gaps"] += 1
            a["gap_min"] += dt.total_seconds() / 60.0 - 1
    errors = Counter()
    for ts, lvl, msg in journal:
        if ts is None:
            continue
        d = ts.astimezone(tz).date()
        if d < first or d > today:
            continue
        a = acc.setdefault(d, {"n": 0, "buy": 0.0, "sell": 0.0, "pv": 0.0, "ev": 0.0, "comp": 0.0, "soc": [], "nsoc": [],
                               "plans": 0, "gaps": 0, "gap_min": 0.0, "fel": 0, "varn": 0})
        if lvl == "fel":
            a["fel"] += 1
            head = str(msg or "").split("\n")[0].strip()[:100]
            if head:
                errors[scrub(head)] += 1
        elif lvl == "varning":
            a["varn"] += 1
    out = ["--- vecka (senaste 7 dygn, lokal tid; nät i kWh; natt = 22-06) ---"]
    for k in range(days):
        d = first + timedelta(days=k)
        a = acc.get(d)
        tag = " (pågår)" if d == today else ""
        if not a or not a["n"]:
            out.append(f"{d}{tag} | ingen data" + (f" | fel {a['fel']} varn {a['varn']}" if a else ""))
            continue
        bat = "inget batteri"
        if a["soc"]:
            bat = f"batteri {min(a['soc']):.0f}-{max(a['soc']):.0f} %"
            if a["nsoc"]:
                bat += f" (natt {min(a['nsoc']):.0f}-{max(a['nsoc']):.0f})"
            bat += f" planbyten {a['plans']}"
        out.append(f"{d}{tag} | nät köpt {a['buy']:.1f} sålt {a['sell']:.1f} | sol {a['pv']:.1f} | bil {a['ev']:.1f} | {bat}"
                   f" | VP {a['comp']:.0f} min | hål {a['gaps']} ({a['gap_min']:.0f} min) | fel {a['fel']} varn {a['varn']}")
    if errors:
        out.append("vanligaste felen: " + " ; ".join(f"{n}x {m}" for m, n in errors.most_common(TOP_ERRORS)))
    return out


def lines(words=None) -> list[str]:
    """Hämtar veckan ur databasen och ger utdragsraderna; tom lista om något saknas (utdraget får aldrig fälla felrapporten)."""
    try:
        import log_scrub
        import local_sql
        import logger
        words = words if words is not None else log_scrub.sensitive_words()
        tz = local_sql.installation_timezone()
        with logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT timestamp, net_power, pv_power_w, battery_soc, ev_power_kw, ev_carport_power_kw, "
                        "compressor_running, battery_plan_id FROM sensor_log "
                        "WHERE timestamp > now() - interval '8 days' ORDER BY timestamp")
            rows = cur.fetchall() or []
            cur.execute("SELECT ts, lvl, msg FROM ew_journal WHERE ts > now() - interval '8 days' "
                        "AND lvl IN ('fel', 'varning') ORDER BY ts")
            journal = cur.fetchall() or []
        now = datetime.now(tz)
        return summarize(rows, journal, tz, now, scrub=lambda s: log_scrub.scrub_line(s, words))
    except Exception:
        return []
