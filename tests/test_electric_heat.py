"""#431: elvärme räknas i skugga. Ingenting skrivs till climate-entiteten."""
import json

import electric_heat


def test_av_eller_okänt_läge_ger_ingen_rad():
    cfg = {"enabled": True, "heaters": [{"entity": "climate.kontor", "min_c": 16, "max_c": 21}]}
    assert electric_heat.plan(None, "EXPENSIVE") == []
    assert electric_heat.plan({"enabled": False, "heaters": cfg["heaters"]}, "CHEAP") == []
    assert electric_heat.plan(cfg, "NORMAL") == []
    assert electric_heat.plan(cfg, None) == []


def test_dyrt_tar_golvet_och_billigt_taket():
    cfg = {"enabled": True, "heaters": [
        {"name": "Kontor", "entity": "climate.kontor", "min_c": 16, "max_c": 21},
    ]}
    cheap = electric_heat.plan(cfg, "CHEAP")
    expensive = electric_heat.plan(cfg, "EXPENSIVE")
    assert len(cheap) == 1 and "21.0" in cheap[0] and "billig el" in cheap[0]
    assert "climate.kontor" in cheap[0] and "Ingenting skickas" in cheap[0]
    assert "16.0" in expensive[0] and "dyr el" in expensive[0]
    assert "Kontor" in expensive[0]


def test_ogiltigt_element_hoppas_över():
    cfg = {"enabled": True, "heaters": [
        {"entity": "sensor.kontor", "min_c": 16, "max_c": 21},
        {"entity": "climate.bad", "min_c": 22, "max_c": 18},
        {"entity": "climate.hall", "min_c": 0, "max_c": 21},
        {"entity": "climate.hall", "min_c": 16, "max_c": 40},
        "climate.trasig",
        {"name": "Kök", "entity": "climate.kok", "min_c": 15, "max_c": 23},
    ]}
    lines = electric_heat.plan(cfg, "CHEAP")
    assert len(lines) == 1
    assert "climate.kok" in lines[0] and "23.0" in lines[0]


def test_effekten_räknas_och_samma_givare_tas_en_gång():
    cfg = {"enabled": True, "heaters": [
        {"name": "Kontor", "entity": "climate.kontor", "min_c": 16, "max_c": 21,
         "power_w": ["sensor.kontor_effekt", "sensor.kontor_extra", "sensor.kontor_effekt"]},
        {"name": "Kök", "entity": "climate.kok", "min_c": 15, "max_c": 23, "power_w": "sensor.kontor_extra"},
        {"entity": "switch.lampa", "power_w": "sensor.lampa"},
        {"entity": "climate.hall", "min_c": 16, "max_c": 21, "power_w": "number.hall"},
        {"entity": "climate.bad", "min_c": 16, "max_c": 21, "power_w": "sensor.bad"},
    ]}
    seen = []

    def read(entity):
        seen.append(entity)
        if entity == "sensor.bad":
            raise TimeoutError("borta")
        return {"sensor.kontor_effekt": 400, "sensor.kontor_extra": -50}.get(entity)

    rows = electric_heat.measured(cfg, read)
    assert rows == [{"name": "Kontor", "w": 350}]
    assert seen == ["sensor.kontor_effekt", "sensor.kontor_extra", "sensor.bad"]
    assert electric_heat.measured({"enabled": False, "heaters": cfg["heaters"]}, read) == []
    assert electric_heat.measured(cfg, None) == []
    line = electric_heat.plan(cfg, "EXPENSIVE", read)[0]
    assert "Drar 350 W" in line and "16.0" in line and "Ingenting skickas" in line


def test_kommentaren_är_av_och_går_att_slå_på():
    block = electric_heat.comment_block([
        {"name": "Sovrum", "entity": "climate.sovrum"},
        {"name": "Fel", "entity": "switch.lampa"},
    ])
    text = "\n".join(block)
    assert text.startswith("#")
    assert "enabled: true" in text
    assert "climate.sovrum" in text
    assert "switch.lampa" not in text
    opened = "\n".join(line[2:] if line.startswith("# ") else line[1:] for line in block if not line.startswith("# El") and not line.startswith("# Energy"))
    cfg = json.loads(json.dumps(__import__("yaml").safe_load(opened)))
    assert cfg["electric_heat"]["enabled"] is True
    assert cfg["electric_heat"]["heaters"][0]["entity"] == "climate.sovrum"
    assert electric_heat.comment_block([]) == []
    assert electric_heat.comment_block([{"entity": "climate.x; rm"}]) == []
