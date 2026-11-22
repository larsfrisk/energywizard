"""COP-uppskattningen när en temperatur saknas (#466 genomgången): en saknad givare är inte 0 °C."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import energy_balance  # noqa: E402


def test_normal_case_is_the_same_formula_as_before():
    assert energy_balance.estimate_cop(45.0, 2.0) == 3.61            # (318,15 / 43) x (0,60 - 0,1125)
    assert energy_balance.estimate_cop(35.0, 0.0) == 4.51            # (308,15 / 35) x (0,60 - 0,0875)


def test_missing_temperature_gives_unknown_not_a_made_up_cop():
    assert energy_balance.estimate_cop(None, 2.0) is None
    assert energy_balance.estimate_cop(45.0, None) is None
    assert energy_balance.estimate_cop(None, None) is None


def test_zero_degrees_brine_is_a_real_value_not_missing():
    assert energy_balance.estimate_cop(45.0, 0.0) == 3.45            # förut ``or 0.0``: 0 °C och saknas gav samma svar


def test_result_is_clamped():
    assert energy_balance.estimate_cop(70.0, 69.0) == 6.5            # delta-T minst 5 K, och COP högst 6,5
    assert energy_balance.estimate_cop(70.0, -30.0) == 1.5           # stor skillnad ger lågt COP, klampat till 1,5


def test_main_uses_it_and_treats_none_as_unknown_heat_power():
    src = (Path(__file__).resolve().parents[1] / "smartbox/main.py").read_text()
    assert "energy_balance.estimate_cop(" in src
    assert 'pump_data["compressor_power_kw"] = None if cop is None' in src
    assert 'get("brine_in_temp") or 0.0' not in src
