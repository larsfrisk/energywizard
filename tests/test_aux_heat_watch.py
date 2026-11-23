import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))
import aux_heat_watch as w


def test_första_avläsningen_ger_ingen_notis():
    assert w.step(10, 5, None) == ([10.0, 5.0], None)


def test_ökning_ger_notis_och_sparas():
    new, inc = w.step(12, 5, [10.0, 5.0])
    assert new == [12.0, 5.0] and inc == [2.0, 0.0]
    assert w.step(12, 5, new)[1] is None


def test_andra_räknaren_räknas_också():
    assert w.step(10, 6, [10.0, 5.0])[1] == [0.0, 1.0]


def test_nollställd_räknare_och_saknade_värden_ger_ingen_notis():
    assert w.step(0, 0, [10.0, 5.0])[1] is None
    assert w.step(None, None, [10.0, 5.0]) == ([10.0, 5.0], None)
    new, inc = w.step(None, 7, [10.0, 5.0])
    assert new == [10.0, 7.0] and inc == [0.0, 2.0]


def test_text():
    m = w.message([1.5, 0.0], -900, 2.54)
    assert "1,5 h" in m and "-900" in m and "2.54" in m


def test_realtid_notis_vid_start_och_inte_igen_förrän_av_i_tio_minuter():
    st, n = w.realtime(1, 0, None, 1000)
    assert n == [1] and st["on"]
    st, n = w.realtime(1, 1, st, 1060)
    assert n is None                                   # redan på
    st, n = w.realtime(0, 0, st, 1120)
    assert n is None and st["on"]                      # kort avbrott
    st, n = w.realtime(1, 0, st, 1180)
    assert n is None                                   # inte av i 10 min -> ingen ny notis
    st, _ = w.realtime(0, 0, st, 2000)
    st, _ = w.realtime(0, 0, st, 2000 + 601)
    assert not st["on"]
    st, n = w.realtime(0, 1, st, 3000)
    assert n == [2]


def test_realtid_saknade_värden_ändrar_inget():
    st = {"on": True, "off_since": None}
    assert w.realtime(None, None, st, 5) == (st, None)


def test_realtidstext():
    m = w.message_realtime([1, 2], 34, -1045, 2.5)
    assert "steg 1 och steg 2" in m and "34 %" in m and "-1045" in m
