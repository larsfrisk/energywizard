"""#559: Skicka felsökningsinfo. Loggen saneras, skickas till samlaren och ger en referens att skriva i ärendet."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import telemetry


class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._d


def test_loggen_saneras_och_en_referens_kommer_tillbaka(monkeypatch):
    sent = {}
    monkeypatch.setattr(telemetry, "house_hash", lambda cfg=None, create=True: "abcd" * 4)
    monkeypatch.setattr(telemetry, "_software_version", lambda: "1.2.test")

    def post(url, json=None, timeout=None):
        sent.update(url=url, json=json)
        return _Resp({"ok": True, "ref": "EW-7K3F2"})

    monkeypatch.setattr(telemetry.requests, "post", post)
    ref = telemetry.send_support_bundle("❌ fel mot 192.168.1.50 och sensor.hemlig_givare", {})
    assert ref == "EW-7K3F2"
    assert sent["url"].endswith("/ingest/support-bundle") and sent["json"]["house"] == "abcd" * 4 and sent["json"]["version"] == "1.2.test"
    assert "192.168.1.50" not in sent["json"]["text"] and "sensor.hemlig_givare" not in sent["json"]["text"]     # sanerad innan den lämnar huset


def test_tom_logg_och_samlarfel_ger_ett_fel_som_anvandaren_far_se(monkeypatch):
    monkeypatch.setattr(telemetry, "house_hash", lambda cfg=None, create=True: "x" * 16)
    with pytest.raises(ValueError):
        telemetry.send_support_bundle("  \n ")
    monkeypatch.setattr(telemetry.requests, "post", lambda *a, **k: _Resp({}, 503))
    with pytest.raises(RuntimeError):
        telemetry.send_support_bundle("något")
    monkeypatch.setattr(telemetry.requests, "post", lambda *a, **k: _Resp({"ok": True}))                          # ingen referens
    with pytest.raises(RuntimeError):
        telemetry.send_support_bundle("något")
