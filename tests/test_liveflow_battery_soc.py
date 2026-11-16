"""Exercise the shared overview battery card in mobile and desktop layouts."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for UI checks")
def test_overview_battery_soc():
    result = subprocess.run(
        ["node", "scripts/test_liveflow_battery_soc.cjs"],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
