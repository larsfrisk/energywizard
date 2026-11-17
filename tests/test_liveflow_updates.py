"""Verify live SVG animation identity across refreshed power readings."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required for UI checks')
def test_flow_updates_preserve_animation_elements():
    result = subprocess.run(
        ['node', 'scripts/test_liveflow_updates.cjs'],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
