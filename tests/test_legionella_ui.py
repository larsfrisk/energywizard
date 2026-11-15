"""Legionella på webben (2026-11-15): intervall och temperatur kan ställas på värmepumpssidan, och senaste gången
varmvattnet nådde temperaturen visas. Kedjan: webbens kontroll -> webdashboard /api/settings-action (tillåten nyckel)
-> ewapp /api/settings (SETTING_RULES med gränser) -> system_settings, som motorn läser (legionella_days/_temp)."""
import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _src(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()


def _setting_rules():
    tree = ast.parse(_src("ewapp/app.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "SETTING_RULES":
            return ast.literal_eval(node.value)
    raise AssertionError("SETTING_RULES saknas")


def test_ewapp_tar_emot_legionella_med_gränser():
    r = _setting_rules()
    assert r["legionella_days"][:3] == ("int", 3, 60)
    assert r["legionella_temp"][:3] == ("float", 55.0, 65.0)
    assert 'if rule[0] == "int":' in _src("ewapp/app.py")


def test_webben_släpper_igenom_och_visar_legionella():
    w = _src("webdashboard/app.py")
    assert '"legionella_days", "legionella_temp"' in w and '"legionella_last"' in w
    js = _src("webdashboard/static/app.js")
    for k in ('id="legdays"', 'id="legtemp"', 'key: "legionella_days"', 'key: "legionella_temp"', "function legLast"):
        assert k in js, k


def test_motorn_läser_samma_kolumner():
    m = _src("smartbox/main.py")
    assert 'cfg.get("legionella_days"' in m and 'cfg.get("legionella_temp"' in m
