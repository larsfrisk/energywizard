"""Veckobrevets rad och ark i appen (scripts/test_ewapp_news.cjs): rollerna, lägena och escaping."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for mobile UI checks")
def test_news_line_and_sheet():
    result = subprocess.run(["node", "scripts/test_ewapp_news.cjs"], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
