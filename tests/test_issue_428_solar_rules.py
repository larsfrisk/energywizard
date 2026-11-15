"""#428: per bil solmål (solladdningen slutar där), starttröskel (kW överskott) och balanspunkt (W över mätaren)."""
import zoneinfo
from datetime import datetime, timedelta

from test_marginal_spapaus import _state

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
NU = datetime(2026, 11, 16, 12, 0, tzinfo=SWE)


def _start(**over):
    from gpm import GlobalPriorityManager
    g = GlobalPriorityManager()
    bas = dict(nissan_connected=True, nissan_charge_completed=False, nissan_soc=60.0, tesla_connected=False,
               grid_import_w=0.0, current_price=0.9, all_prices=[0.9] * 96)
    bas.update(over)
    a = g.evaluate(_state(NU, **bas))
    return g, a


def test_starttröskeln_väntar_på_större_överskott():
    g, _ = _start(avg_net_w=-2500.0, nissan_solar_start_kw=4.0)
    assert not g.ev_solar_charge_active
    g, _ = _start(avg_net_w=-4500.0, nissan_solar_start_kw=4.0)
    assert g.ev_solar_charge_active


def test_utan_tröskel_som_förut():
    g, _ = _start(avg_net_w=-2000.0)
    assert g.ev_solar_charge_active


def test_över_solmålet_solladdar_inte():
    g, _ = _start(avg_net_w=-4000.0, nissan_soc=82.0, nissan_solar_soc=80)
    assert not g.ev_solar_charge_active
    g, _ = _start(avg_net_w=-4000.0, nissan_soc=70.0, nissan_solar_soc=80)
    assert g.ev_solar_charge_active


def test_balanspunkten_flyttar_nollan():
    # Laddar 10 A 1-fas; netto +100 W (köp). Med balanspunkt +300 W ska strömmen öka, inte minska.
    g, _ = _start(avg_net_w=-2300.0, nissan_solar_balance_w=300)
    assert g.ev_solar_charge_active
    g.ev_solar_target_amps = 10
    g.ev_solar_last_eval_time = NU - timedelta(minutes=6)
    g.avg_net_history = [100.0] * 5
    g.evaluate(_state(NU + timedelta(minutes=6), nissan_connected=True, nissan_charge_completed=False, nissan_soc=60.0,
                      tesla_connected=False, avg_net_w=100.0, grid_import_w=100.0, current_price=0.9, all_prices=[0.9] * 96,
                      nissan_solar_balance_w=300))
    assert g.ev_solar_target_amps == 11
