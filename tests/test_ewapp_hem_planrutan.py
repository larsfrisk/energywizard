"""Hem-fliken (2026-11-20): vid stor text får planrutan krympa men inte försvinna, annars blir det 150-270 px tomt längst ner.
Mätt i en emulerad telefon mot den riktiga appen; här vaktas bara att regeln som döljer hela rutan inte kommer tillbaka."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "ewapp" / "static" / "style.css").read_text(encoding="utf-8")


def test_plannow_is_never_hidden_as_a_whole_at_large_text():
    assert not re.search(r"\.page\.t[45][^{]*\.plannow\s*\{\s*display\s*:\s*none", CSS)


def test_plannow_shrinks_to_one_row_at_t5_for_both_row_variants():
    assert ".page.t5 .flowcard ~ .plannow .pnrow2:nth-child(n+2) { display:none; }" in CSS
    assert re.search(r"\.page\.t5 \.flowcard ~ \.plannow \.pnrow:nth-child\(n\+2\)\s*\{\s*display:none", CSS)
    assert "-webkit-line-clamp:2" in CSS
