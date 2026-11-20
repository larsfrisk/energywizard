"""Översiktens måltemperatur är det beställda börvärdet (#517)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fn():
    tree = ast.parse((ROOT / "webdashboard" / "app.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "shown_indoor_target")
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "shown_indoor_target", "exec"), ns)
    return ns["shown_indoor_target"]


def test_bestallt_borvarde_gar_fore_installningen():
    show = _fn()
    assert show(17.5, 21.0) == 17.5
    assert show(None, 21.0) == 21.0


def test_oversikten_laser_target_room_temp():
    src = (ROOT / "webdashboard" / "app.py").read_text(encoding="utf-8")
    assert 'shown_indoor_target(_n(row.get("target_room_temp"))' in src
    js = (ROOT / "webdashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "indoor_target.toFixed(0)" not in js
    assert js.count("fmt(d.indoor_target, 1,") == 3
