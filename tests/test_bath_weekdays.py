"""Badtiderna i engelsk vy visade Tisdag-Fredag på svenska (2026-11-15). Alla veckodagar ska finnas i katalogerna,
och raderna visar "→ nästa dag" när tiden går över midnatt."""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_alla_veckodagar_översätts():
    for lang in ("en", "cs"):
        cat = json.load(open(os.path.join(ROOT, "smartbox", "i18n", f"{lang}.json"), encoding="utf-8"))
        for d in ("Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag", "→ nästa dag"):
            assert d in cat, (lang, d)


def test_nästa_dag_visas():
    for p in ("webdashboard/static/app.js", "ewapp/static/app.js"):
        assert "→ nästa dag" in open(os.path.join(ROOT, p), encoding="utf-8").read()
