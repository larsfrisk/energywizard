"""enable_switch (Sigenergy Remote EMS): brytaren slås på en gång och bekräftas innan ett läge väljs."""
from unittest.mock import patch

import pytest

from drivers.battery_generic import GenericBatteryDriver

SW, SEL = "switch.sigen_remote_ems", "select.sigen_remote_ems_mode"


def _drv(**extra):
    return GenericBatteryDriver(entities={"mode_select": SEL, "enable_switch": SW, **extra},
                                modes={"charge": "Command Charging (Grid First)", "auto": "Maximum Self Consumption"})


class Ha:
    """Minimal HA: switch-läge och anrop i ordning."""
    def __init__(self, switch, turns_on_after=None):
        self.switch, self.calls, self.turns_on_after, self.polls = switch, [], turns_on_after, 0

    def raw(self, e):
        return self.switch if e == SW else None

    def set_switch(self, e, on):
        self.calls.append(("switch", e, on))
        return True

    def set_select(self, e, opt, **kw):
        self.calls.append(("select", e, opt))
        return True

    def update_states(self):
        self.polls += 1
        if self.turns_on_after is not None and self.polls >= self.turns_on_after:
            self.switch = "on"


def _run(drv, ha, intent="charge"):
    with patch("drivers.battery_generic.homeassistant._get_raw_state", ha.raw), \
         patch("drivers.battery_generic.homeassistant.set_switch", ha.set_switch), \
         patch("drivers.battery_generic.homeassistant.set_select", ha.set_select), \
         patch("drivers.battery_generic.homeassistant.update_states", ha.update_states), \
         patch("drivers.battery_generic.time.sleep"):
        return drv._apply(intent)


def test_redan_pa_skriver_inte_om_brytaren():
    ha = Ha("on")
    assert _run(_drv(), ha) is True
    assert ha.calls == [("select", SEL, "Command Charging (Grid First)")]


def test_av_slas_pa_en_gang_bekraftas_och_sedan_valjs_lage():
    ha = Ha("off", turns_on_after=2)
    assert _run(_drv(), ha) is True
    assert ha.calls == [("switch", SW, True), ("select", SEL, "Command Charging (Grid First)")]   # brytaren först, en gång


def test_aldrig_bekraftad_ger_fel_och_inget_lage():
    ha = Ha("off", turns_on_after=None)
    times = iter([0.0, 1.0, 10.0, 40.0, 70.0])
    with patch("drivers.battery_generic.time.monotonic", lambda: next(times)):
        assert _run(_drv(), ha) is False
    assert ha.calls == [("switch", SW, True)]          # ingen lägesändring, ingen omskrivning


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
def test_otillgangligt_skriver_ingenting(state):
    ha = Ha(state)
    assert _run(_drv(), ha) is False
    assert ha.calls == []


def test_utan_enable_switch_som_forut():
    drv = GenericBatteryDriver(entities={"mode_select": SEL}, modes={"auto": "Maximum Self Consumption"})
    ha = Ha("off")
    assert _run(drv, ha, "auto") is True
    assert ha.calls == [("select", SEL, "Maximum Self Consumption")]
