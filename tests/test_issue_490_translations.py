"""Run the browser's real English/Czech notification translation regressions."""
from pathlib import Path
import subprocess


def test_mobile_notification_translations():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "tests/test_issue_490_translations.cjs"], cwd=root, check=True)
