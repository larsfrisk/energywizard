"""#562: /api/economy gav "Internal server error" för alla på 1.2.118 eller senare. Raden som tar fram dagens datum anropade
local_sql.installation_timezone(), men local_sql är importerad som funktionen, inte modulen. Endast databasen och
besparingsberäkningarna ersätts här; allt annat i svaret byggs på riktigt, så en sådan miss syns."""
import asyncio
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webdashboard"))
sys.path.insert(0, str(ROOT / "smartbox"))


def _app():
    for k, v in (("POSTGRES_USER", "u"), ("POSTGRES_PASSWORD", "p"), ("POSTGRES_DB", "d")):
        os.environ.setdefault(k, v)
    sys.modules.pop("app", None)
    cwd = os.getcwd()
    os.chdir(ROOT / "webdashboard")
    try:
        return importlib.import_module("app")
    finally:
        os.chdir(cwd)


def test_ekonomisidans_api_bygger_svaret(monkeypatch):
    mod = _app()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    mod.ENGINE = engine
    monkeypatch.setattr(mod, "_latest_row", lambda c: {"price": 1.5})
    monkeypatch.setattr(mod, "_price_24h", lambda c: None)
    import savings
    monkeypatch.setattr(savings, "money_rows", lambda c, days=40: [])
    monkeypatch.setattr(savings, "daily_rows", lambda c, days=40: [])
    out = asyncio.run(mod.api_economy())
    assert out["ok"] is True and out["price"] == 1.5 and "money" in out and "timing" in out


def test_ingen_modulattribut_pa_funktionen_local_sql():
    """local_sql är funktionen: ingenting ska anropa attribut på den (det var felet)."""
    for f in ("webdashboard/app.py", "ewapp/app.py", "smartbox/main.py"):
        assert "local_sql.installation_timezone" not in (ROOT / f).read_text(encoding="utf-8"), f
