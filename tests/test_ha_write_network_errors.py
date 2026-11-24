"""#588-#595: nätverksfel mot HA i skrivfunktionerna är drift (⚠️), inte ett programfel som blir ett GitHub-ärende."""
import os
import sys
from unittest.mock import patch

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))
import homeassistant


def _out(capsys, exc, fn, *a):
    with patch.object(homeassistant.requests, "post", side_effect=exc), patch.object(homeassistant.requests, "get", side_effect=exc):
        fn(*a)
    return capsys.readouterr().out


def test_connectionerror_och_invalidurl_blir_varning(capsys):
    for exc in (requests.ConnectionError("nere"), requests.exceptions.InvalidURL("fel adress"), requests.Timeout("tid")):
        o = _out(capsys, exc, homeassistant.toggle_spa_plug, True, "switch.spa")
        assert o.startswith("⚠️") and "❌" not in o
        o = _out(capsys, exc, homeassistant.set_gecko_target, 38.0, "number.spa_target")
        assert "❌" not in o


def test_oväntat_fel_förblir_fel(capsys):
    o = _out(capsys, ValueError("konstigt"), homeassistant.toggle_spa_plug, True, "switch.spa")
    assert o.startswith("❌")


def test_http_fel_förblir_fel(capsys):
    o = _out(capsys, requests.HTTPError("500 Server Error"), homeassistant.toggle_spa_plug, True, "switch.spa")
    assert o.startswith("❌")
