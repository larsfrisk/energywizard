import ev_schedule_auto as a


def week(**soc):
    return {d: {"target_soc": soc.get(f"d{d}", 100)} for d in range(7)}


def test_dagens_egen_niva_behalls():
    assert a.soc_for(week(d2=50), 2) == 50


def test_annars_den_vanligaste_lagre_nivan_bland_ovriga_dagar():
    w = week(d0=50, d1=50, d3=60)
    assert a.soc_for(w, 5) == 50


def test_inget_lagre_satt_ger_100():
    assert a.soc_for(week(), 3) == 100


def test_saknade_eller_trasiga_varden_ger_100_och_golv_20():
    assert a.soc_for({}, 0) == 100
    assert a.soc_for({0: {"target_soc": None}}, 0) == 100
    assert a.soc_for(week(d1=10), 1) == 20
