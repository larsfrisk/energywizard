"""2026-11-15: när rumsgivarna saknades en minut tog styrningen pumpens fasta 20,0 °C, och rumsåterkopplingen höjde
börvärdet ("nära golvet"). Givarnas senaste värde behålls nu i 15 minuter."""
import ast
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "smartbox"))

import indoor_hold

T = datetime(2026, 11, 15, 9, 1)


def test_kort_glapp_behåller_givarnas_värde():
    assert indoor_hold.choose(None, 20.0, True, 21.9, T - timedelta(minutes=1), T) == (21.9, "givare (senaste)")


def test_långt_glapp_tar_pumpens_värde():
    assert indoor_hold.choose(None, 20.0, True, 21.9, T - timedelta(minutes=16), T)[0] == 20.0


def test_utan_valda_givare_används_pumpen():
    assert indoor_hold.choose(None, 20.0, False, None, None, T)[0] == 20.0


def test_givare_som_svarar_går_först():
    assert indoor_hold.choose(21.4, 20.0, True, 21.9, T, T) == (21.4, "givare")


def test_main_använder_hållet_vid_glapp():
    src = open(os.path.join(ROOT, "smartbox", "main.py"), encoding="utf-8").read()
    ast.parse(src)
    assert "indoor_hold.choose(None, pump_indoor_temp" in src and "last_valid_ha_temp = indoor_temp" in src
