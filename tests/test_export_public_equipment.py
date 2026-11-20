"""scripts/export_public_equipment.py: bara kända tillverkare, rätt kategori, aldrig personnamn eller modeller."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("epe", Path(__file__).resolve().parents[1] / "scripts" / "export_public_equipment.py")
epe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(epe)

STATS = {"active": 5, "equipment": {
    "car": {"generic_ev@Åkoda#Enyaq": 3, "generic_ev@Škoda Auto#Enyaq": 2, "generic_ev@Aqara#Smart Smoke Detector EU": 2,
            "generic_ev@Mammotion#LUBA 3": 1, "tesla@Tesla#Model Y": 4, "tesla": 1},
    "battery": {"generic@marq24#Loadpoint": 1, "generic@Solis#S6-EH3P": 3, "ftw-sungrow": 3, "generic@Sungrow#SH10": 1},
    "meter": {"ha@Gabriel C.#M2HT": 1, "ha@Tibber#Pulse": 22},
    "heatpump": {"ha_entities@F750#Cu": 1, "ha_entities@NIBE Energy Systems#S735": 2, "ha_entities@Pojkebo#X": 1},
}}


def names(cat):
    return {x["name"]: x["n"] for x in epe.build(STATS)["equipment"][cat]}


def test_modeller_och_stavningar_samlas_per_marke():
    assert names("car") == {"Škoda": 5, "Tesla": 5}


def test_felvalda_enheter_och_personnamn_visas_aldrig():
    assert "Aqara" not in names("car") and "Mammotion" not in names("car")
    assert names("battery") == {"Sungrow": 4, "Solis": 3}
    assert names("meter") == {"Tibber": 22}
    assert names("heatpump") == {"NIBE": 3}


def test_ingen_modell_i_utdata():
    assert "Enyaq" not in str(epe.build(STATS)) and "S6-EH3P" not in str(epe.build(STATS))
