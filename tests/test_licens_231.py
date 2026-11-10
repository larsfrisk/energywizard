"""#231: licenstext och upstream-notiser följer med i repot och i bilderna; inga påståenden om särskilt tillstånd
och inget telemetrivillkor som inskränker AGPL."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_licens_i_varje_bild():
    lic = (ROOT / "LICENSE").read_text()
    for d in ("smartbox", "ewapp", "webdashboard"):
        assert (ROOT / d / "LICENSE").read_text() == lic, f"{d}/LICENSE skiljer sig från rotens LICENSE"
    assert "COPY LICENSE" in (ROOT / "smartbox/Dockerfile").read_text()
    assert "cp /src/LICENSE" in (ROOT / "ha-addon/smartbox/Dockerfile").read_text()


def test_ftw_upstream_notiser_och_andringar():
    d = ROOT / "smartbox/ftw_drivers"
    for f in ("UPSTREAM-LICENSE", "UPSTREAM-NOTICE", "UPSTREAM-LICENSING.md", "UPSTREAM-THIRD_PARTY_NOTICES.md"):
        assert (d / f).stat().st_size > 500, f
    notice = (d / "NOTICE.md").read_text()
    assert "har gett sitt OK" not in notice and "deye-svk.lua" in notice


def test_inget_anvandningsvillkor_for_telemetrin():
    for f in ("README.md", "README.en.md", "ha-addon/smartbox/DOCS.md", "docs/kunskapsbank/faq.html", "docs/en/kunskapsbank/faq.html"):
        t = (ROOT / f).read_text()
        assert "villkor för att använda" not in t and "condition for using" not in t, f
        assert "AGPL" in t, f
