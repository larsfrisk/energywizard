import os, sys
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
