"""#598: tid i förväg för bilvärmen, lärd ur bilens värmepass och beroende av hur kall bilen är."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))
import car_preheat as p


def session(t_start, t0, rate_per_min, minutes, state="heat_cool", step_s=60):
    """Ett värmepass med jämn stigning, avläsning varje minut; avslutas med en rad där klimatet är av."""
    rows = [(t_start + i * step_s, state, t0 + rate_per_min * i) for i in range(int(minutes))]
    rows.append((t_start + minutes * step_s, "off", t0 + rate_per_min * minutes))
    return rows


def history(n=5, t0=5.0, rate=1.0, minutes=16):
    rows = []
    for k in range(n):
        rows += session(1_000_000 + k * 86400, t0, rate, minutes)
    return rows


def test_lär_sig_minuter_per_grad():
    mpd = p.minutes_per_degree(p.sessions(history()), 21.0)
    assert 0.9 < mpd < 1.1


def test_för_få_pass_ger_grundmodell():
    s = p.sessions(history(n=2))
    assert p.minutes_per_degree(s, 21.0) is None
    assert p.predict(None, 5.0, 21.0, 0.0) == p.old_model(0.0)


def test_kallare_start_ger_längre_tid():
    mpd = 1.0
    kall = p.predict(mpd, -5.0, 21.0, -5.0)
    ljummen = p.predict(mpd, 8.0, 21.0, -5.0 + 20)     # ute 15: kupén 8 gäller (inom marginalen)
    assert kall > ljummen
    assert abs(kall - (26 * 1.0 + p.MARGIN_MIN)) < 1e-6


def test_gammal_varm_avläsning_kapas_av_utetemperaturen():
    # bilen visar 20 °C (gammalt) men det är -5 ute: starten räknas från ute + 5 = 0 °C, inte 20
    assert p.predict(1.0, 20.0, 21.0, -5.0) == p.predict(1.0, 0.0, 21.0, -5.0)


def test_okänd_starttemp_använder_utetemperaturen_och_klampas():
    assert p.predict(1.0, None, 21.0, 21.0) == p.MIN_MIN                  # redan varmt: minimitid
    assert p.predict(5.0, None, 21.0, -20.0) == p.MAX_MIN


def test_gammal_temperatur_som_hoppar_räknas_inte():
    # Tesla via HA: temperaturen står still och hoppar rakt till målet (2 olika avläsningar)
    rows = []
    for k in range(5):
        t = 2_000_000 + k * 86400
        rows += [(t, "heat_cool", 2.0), (t + 60, "heat_cool", 2.0), (t + 600, "heat_cool", 21.0), (t + 660, "off", 21.0)]
    assert p.minutes_per_degree(p.sessions(rows), 21.0) is None


def test_pass_över_ett_dygn_räknas_inte():
    rows = session(1_000_000, 5.0, 1.0, 16) * 1 + session(1_200_000, 5.0, 0.0002, 3000)
    s = p.sessions(rows)
    assert p.minutes_per_degree(s, 21.0) is None
