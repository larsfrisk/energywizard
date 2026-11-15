"""ML-styrt startvärde för varmvattnet (Emil 2026-11-15).

Pumpen startar varmvattnet när en viktad tanktemperatur sjunker under startvärdet. På Thermia väger givaren längre ned
i tanken 65 % (INFL. STARTGIV.), och startvärdet går att ställa mellan 30 och 55 °C. Stoppvärdet (TOPPV. STOPP,
toppvärmningen/legionella) rörs aldrig.

Val, utifrån de inlärda varmvattenvanorna (sannolikhet för tappning per veckodag och timme, learning.py) och priset:
  - billigt och en tappning väntas inom 12 h, och det här är bland de billigaste kvartarna före den -> FILL (fyll tanken)
  - dyrt och ingen tappning väntas de närmaste 2 h -> LOW (vänta så länge det går)
  - dyrt men en tappning väntas snart -> NORMAL_EXPENSIVE (som förut)
  - annars som förut (billigt NORMAL_CHEAP)
Legionella, felskydd (under 38 °C), minuspris och solöverskott går före (de sätts senare i gpm).
Uttryckt som gpm:s varmvattenmål (start = mål - 5, water_setpoints.plan).
"""
from datetime import timedelta

DRAW_P = 0.55            # samma tröskel som Prio 5.8 (förvärmning inför en trolig tappning)
START_LOW = 30.0
START_NORMAL_EXPENSIVE = 35.0
START_NORMAL_CHEAP = 45.0
START_FILL = 50.0
CHEAP_SHARE = 0.25       # bland de billigaste 25 % av kvartarna före tappningen


def _p(profile, t):
    return float((profile or {}).get((t.weekday(), t.hour), 0.0) or 0.0)


def next_draw(profile, now, hours=12):
    """Första hela timme inom `hours` där en tappning är trolig, eller None."""
    for h in range(0, hours + 1):
        t = now + timedelta(hours=h)
        if _p(profile, t) >= DRAW_P:
            return t.replace(minute=0, second=0, microsecond=0)
    return None


def choose_start(now, mode, profile, prices_today, quarter_index):
    """(startvärde °C, förklaring). prices_today: dagens kvartspriser (96 st), quarter_index: nuvarande kvart."""
    draw = next_draw(profile, now)
    if mode == "EXPENSIVE":
        soon = draw is not None and draw - now <= timedelta(hours=2)
        if soon:
            return START_NORMAL_EXPENSIVE, f"dyrt, men en tappning väntas kl {draw:%H}"
        return START_LOW, "dyrt och ingen tappning väntas de närmaste 2 timmarna"
    if draw is not None and prices_today and 0 <= quarter_index < len(prices_today):
        end = min(len(prices_today), quarter_index + max(1, int((draw - now).total_seconds() // 900)) + 1)
        window = [p for p in prices_today[quarter_index:end] if p is not None]
        if window:
            limit = sorted(window)[max(0, int(len(window) * CHEAP_SHARE) - 1)]
            if prices_today[quarter_index] is not None and prices_today[quarter_index] <= limit:
                return START_FILL, f"billigt och bland de billigaste kvartarna före nästa troliga tappning kl {draw:%H}"
    return START_NORMAL_CHEAP, "billigt"


def target_for_start(start):
    """gpm:s varmvattenmål som ger detta startvärde (water_setpoints.plan: start = mål - 5)."""
    return start + 5.0
