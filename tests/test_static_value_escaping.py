"""Webbens och appens JS: varje ``value="${…}"`` går genom esc(), så ett citattecken i ett fält kan inte bryta sidan eller lägga in
markup (idé från FTW 0.165.3: setup och inställningar klippte fält vid ett citattecken)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["webdashboard/static/app.js", "ewapp/static/app.js"]


def test_every_value_attribute_interpolation_is_escaped():
    bad = []
    for f in FILES:
        for i, line in enumerate((ROOT / f).read_text(encoding="utf-8").split("\n"), 1):
            for m in re.finditer(r'value="\$\{([^}]*)\}"', line):
                if not m.group(1).strip().startswith("esc("):
                    bad.append(f"{f}:{i}: {m.group(0)[:80]}")
    assert not bad, "oescapade value=-attribut:\n" + "\n".join(bad)
