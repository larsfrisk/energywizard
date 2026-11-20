"""#391: vägkartan ska följa rekommendationen, inte börja med en generell evcc-tolk."""
from pathlib import Path


def test_vagkartan_foljer_evcc_rekommendationen():
    text = " ".join((Path(__file__).resolve().parents[1] / "ROADMAP.md").read_text(encoding="utf-8").split())
    assert "Börja med (1)" not in text
    assert "En generell tolk för mallarna byggs inte först (#391)" in text
    assert "i skuggläge tills en riktig installation verifierat styrningen (#395)" in text
    assert "GET /api/state" in text
    assert "Inga skrivningar mot evcc." in text
