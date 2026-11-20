

def test_okant_kompressorlage_star_inte_som_vilar():
    """#184: NIBE via myUplink utan kompressorgivare visades som 'Vilar' medan huset drog 5 kW."""
    import live_flow
    d = live_flow.nodes({"compressor_power_kw": 0.0, "indoor_temp": 17.7, "net_power": 4800})
    vp = next(n for n in d["nodes"] if n["key"] == "varmepump")
    assert vp["detail"] == "inne 17.7 °C" and not vp["active"]
    d = live_flow.nodes({"compressor_running": 0, "compressor_power_kw": 0.0, "indoor_temp": 17.7})
    assert next(n for n in d["nodes"] if n["key"] == "varmepump")["detail"] == "Vilar · inne 17.7 °C"


def test_varmepumpen_visar_uppmatt_el_inte_kompressorns_varmeeffekt():
    """2026-11-20: compressor_power_kw var 11,5 kW (värme) medan pumpen drog 2,7 kW el. Den uppmätta elen ska gå före."""
    import live_flow
    row = {"compressor_running": 1, "compressor_power_kw": 11.5, "indoor_temp": 21.0}
    heat = lambda **kw: next(n for n in live_flow.nodes(row, **kw)["nodes"] if n["key"] == "varmepump")
    assert heat()["w"] == 11500                                           # utan mätvärde som förut
    assert heat(pump_w=2718)["w"] == 2718 and heat(pump_w=2718)["active"] is True
    assert heat(pump_w=0)["w"] == 0                                       # pumpen står: 0 W, inte värmeeffekten
    assert heat(pump_w=float("nan"))["w"] == 11500                        # ogiltigt mätvärde ignoreras
