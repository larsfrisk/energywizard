"""#512: kunskapsbanken ska namnge de märken guiden kan läsa direkt."""
from pathlib import Path

import discovery


def test_direktlasningen_star_i_kunskapsbanken():
    root = Path(__file__).resolve().parents[1]
    folder = Path(discovery.__file__).parent / "ftw_drivers"
    pages = {
        "sv": (root / "docs/kunskapsbank/husbatteri.html").read_text(encoding="utf-8"),
        "en": (root / "docs/en/kunskapsbank/home-battery.html").read_text(encoding="utf-8"),
        "vx": (root / "docs/kunskapsbank/vaxelriktare.html").read_text(encoding="utf-8"),
    }
    drivers = discovery._FTW_WHEN_HA_CANNOT_CONTROL
    assert [row[1] for row in drivers] == ["deye", "sigenergy", "solinteg", "pixii"]
    for _rx, driver, also_solar in drivers:
        assert (folder / f"{driver}.lua").is_file()
        for text in pages.values():
            assert driver in text.casefold()
        solar_sv = "kan också läsa solproduktionen" in pages["sv"]
        solar_en = "can also read solar production" in pages["en"]
        assert solar_sv and solar_en
        if not also_solar:
            assert driver == "pixii"
            assert "Pixii läser bara batteriet" in pages["sv"]
            assert "Pixii reads only the battery" in pages["en"]
    assert "Inte provad på riktig hårdvara" in pages["sv"]
    assert "inte provad på riktig hårdvara" in pages["vx"].casefold()
    assert "Not run on real hardware" in pages["en"]
    assert "has been run on real hardware" in pages["en"]
