"""Flödesrutan märker en manuell laddning ("Ladda nu") i appen och på webben."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for UI checks")
def test_manual_charge_label():
    result = subprocess.run(["node", "scripts/test_liveflow_manual_charge.cjs"],
                            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
