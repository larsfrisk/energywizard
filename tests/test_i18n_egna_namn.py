"""Namn som användaren eller Home Assistant gett (enheter, radiatorer, områden, hus) ska inte översättas: en givare
som heter "Varmvatten" ska inte bli "Hot water" i engelsk vy. De visas inom data-noi18n (2026-11-15)."""
import os

JS = open(os.path.join(os.path.dirname(__file__), "..", "webdashboard", "static", "app.js"), encoding="utf-8").read()


def test_enhets_och_husnamn_översätts_inte():
    for frag in ('<b data-noi18n>${esc(c.device_name)}</b>', '<span data-noi18n>${esc(d.heat_pump.device_name || "")}</span>',
                 '<b data-noi18n>${esc(r.name)}</b>', '<span data-noi18n>${esc(r.area)}</span>',
                 '<span data-noi18n>${esc(c.device_name)}</span>', '<span data-noi18n>${esc(h.label)}</span>'):
        assert frag in JS, frag


def test_enhetsnamn_escapas():
    assert "<b>${c.device_name}</b>" not in JS and "checked> ${c.device_name}</label>" not in JS
