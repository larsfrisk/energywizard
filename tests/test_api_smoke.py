"""Rökprov av webbens API (#562): ingen /api/-väg får ge 500. Ett fel som bara syns när en sida öppnas (som Ekonomi i 1.2.118)
stoppas här i stället för hos användarna. Själva provet ligger i tests/smoke_api.py och körs i en egen process."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alla_get_vagar_i_webben_svarar_utan_500():
    env = dict(os.environ)
    env.setdefault("TEST_DB_HOST", "localhost")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "smartbox"), str(ROOT / "webdashboard"), env.get("PYTHONPATH", "")])
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "smoke_api.py")], env=env, capture_output=True, text=True, timeout=420)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, "Webbens API: " + "\n".join(l for l in out.splitlines() if l.startswith("FEL") or "vägar" in l or "Error" in l)[-1500:]
