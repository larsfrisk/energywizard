"""Egna laster (`loads:` i installationen): tolkningen av config-filen."""
from house_config import extra_loads


def test_tom_eller_saknad_ger_inget():
    assert extra_loads({}) == []
    assert extra_loads({"loads": None}) == []
    assert extra_loads({"loads": "fel"}) == []


def test_namn_och_effektsensor():
    cfg = {"loads": [{"name": "Tvättmaskin", "power": "sensor.tvatt_power"}]}
    assert extra_loads(cfg) == [{"name": "Tvättmaskin", "entities": ["sensor.tvatt_power"]}]


def test_lista_summeras_och_namn_utelamnat_ger_entiteten():
    cfg = {"loads": [{"name": "Bastu", "power": ["sensor.a", " sensor.b "]}, {"power": "sensor.c"}]}
    assert extra_loads(cfg) == [{"name": "Bastu", "entities": ["sensor.a", "sensor.b"]},
                                {"name": "sensor.c", "entities": ["sensor.c"]}]


def test_ogiltiga_poster_och_dubbletter_hoppas_over():
    cfg = {"loads": ["text", {"name": "Utan sensor"}, {"name": "X", "power": ""}, {"name": "A", "power": "sensor.a"},
                     {"name": "A", "power": "sensor.b"}]}
    assert extra_loads(cfg) == [{"name": "A", "entities": ["sensor.a"]}]
