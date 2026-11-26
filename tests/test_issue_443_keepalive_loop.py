"""#443 (Lars): Solis RC släpper tvångsladdning/håll efter sin RC Timeout (standard 5 min). Håll vid liv måste därför
anropas i 10-sekundersloopen, inte bara i kvartsstyrningen - och aldrig under säkerhetsregler eller utan styrning."""
import os
import re

SRC = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()


def test_håll_vid_liv_i_snabbloopen():
    fast = SRC.split("SNABB TASK", 1)[1].split("tibber = homeassistant.read_power_meter()", 1)[0]
    assert "battery_driver.refresh()" in fast
    assert 'battery_cfg["control"] == "styr"' in fast and "battery_control.NO_KEEPALIVE_RULES" in fast
    assert re.search(r'getattr\(battery_driver, "_keepalive"', fast)


def test_håll_på_reservnivån_förnyas_men_övriga_säkerhetsregler_inte():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
    import battery_control as bc
    assert "reserve" in bc.SAFETY_RULES and "reserve" not in bc.NO_KEEPALIVE_RULES
    assert {"stale", "fuse", "fuse_cap", "peak", "soc_limit"} <= bc.NO_KEEPALIVE_RULES
    assert "battery_control.SAFETY_RULES" not in SRC.split("battery_driver.refresh()")[0][-600:]
