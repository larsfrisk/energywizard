"""2026-11-15: efter en omstart var laddboxens fasläge okänt (Easee går inte att läsa). Solladdningen räknade ström för
1 fas (19 A) och skickade den, men laddboxen körde 3 faser: 11 A x 3 = 7,6 kW på 4,4 kW sol -> nätköp. Okänt fasläge
räknas nu som 3 faser för en bil som kan ladda 3-fas, så motorn växlar uttryckligen till 1 fas först."""
import zoneinfo
from datetime import datetime

from test_marginal_spapaus import _state

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
NU = datetime(2026, 11, 15, 13, 22, tzinfo=SWE)


def _start(phases, shaky=True):
    from gpm import GlobalPriorityManager
    g = GlobalPriorityManager()
    a = g.evaluate(_state(NU, tesla_soc=29.0, tesla_phases=phases, solar_is_shaky=shaky, avg_net_w=-4375.0,
                          grid_import_w=0.0, current_price=0.9, all_prices=[0.9] * 96))
    assert g.ev_solar_charge_active
    return g, a


def test_okänt_fasläge_växlar_till_1_fas_innan_ström_ges():
    g, a = _start(None)
    assert g.ev_solar_target_phases == 1
    assert a.get("tesla_set_phases") == 1 and a.get("tesla_limit_a") == 0, (a.get("tesla_set_phases"), a.get("tesla_limit_a"))


def test_känt_1_fasläge_ger_ström_direkt():
    g, a = _start("SinglePhase")
    assert a.get("tesla_set_phases") is None and a.get("tesla_limit_a", 0) >= 6
