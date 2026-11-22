import spa_error_watch as w


def test_forsta_avlasningen_ger_ingen_notis_men_sparas():
    assert w.step("OverTemp", None) == ("OverTemp", None)
    assert w.step("None", None) == ("", None)


def test_kvarstaende_fel_meddelas_inte_igen():
    assert w.step("OverTemp", "OverTemp") == ("OverTemp", None)


def test_nytt_eller_annat_fel_meddelas_en_gang():
    seen, msg = w.step("OverTemp", "")
    assert (seen, msg) == ("OverTemp", "OverTemp")
    assert w.step("OverTemp", seen)[1] is None
    assert w.step("Flow", "OverTemp") == ("Flow", "Flow")


def test_tillbaka_till_inget_fel_nollstaller_sa_samma_fel_kan_komma_igen():
    seen, msg = w.step("None", "OverTemp")
    assert (seen, msg) == ("", None)
    assert w.step("OverTemp", seen) == ("OverTemp", "OverTemp")


def test_otillganglig_sensor_andrar_ingenting():
    for t in ("unavailable", "unknown", None, ""):
        assert w.step(t, "OverTemp") == ("OverTemp", None)
        assert w.step(t, "") == ("", None)
