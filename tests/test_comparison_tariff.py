"""Comparison tariff isolation and explicit currency/VAT assumptions."""
from datetime import datetime, timezone
import pytest
import comparison_tariff as T
import battery_shadow as B

MODEL = dict(currency='SEK',spot_includes_vat=False,buy_spot_factor=1.25,
             buy_extra=.4,sell_positive_spot_factor=.95,sell_negative_spot_factor=1,sell_extra=.1)


@pytest.mark.parametrize('spot,buy,sell',[(-1,-.85,-.9),(0,.4,.1),(2,2.9,2)])
def test_effective_tariffs_use_explicit_input_scale_and_offset_last(spot,buy,sell):
    assert T.prices(T.validate(MODEL),spot)==pytest.approx((buy,sell))


@pytest.mark.parametrize('change',[{'currency':'sek'},{'currency':'private-currency'},
    {'spot_includes_vat':1},{'buy_spot_factor':-1},{'sell_negative_spot_factor':11},
    {'buy_extra':True},{'sell_extra':float('nan')},{'sell_positive_spot_factor':float('inf')},
    {'token':'private'}])
def test_invalid_configuration_is_refused_before_worker_start(change):
    monitor=B.Monitor()
    assert not monitor.submit({'enabled':True,'allowed_intents':['auto'],'tariff_model':MODEL|change},
        {'control':'samarbete','plan':True,'capacity_kwh':10},{'soc_pct':50},{},
        now=datetime.now(timezone.utc),shadow=True)
    assert monitor._thread is None and monitor._queue.empty()


def test_missing_fields_rejected_and_default_is_absent():
    assert T.validate(None) is None
    with pytest.raises(ValueError):T.validate({'currency':'SEK'})


@pytest.mark.parametrize('spot',[True,float('nan'),float('inf')])
def test_invalid_prices_are_not_converted_into_tariffs(spot):
    with pytest.raises(ValueError):T.prices(MODEL,spot)


def test_overflow_is_refused():
    with pytest.raises(ValueError):T.prices(MODEL|{'buy_spot_factor':10},1e308)


def test_queued_model_is_frozen_and_default_has_no_override(monkeypatch):
    monkeypatch.setattr(B.threading.Thread,'start',lambda self:None)
    model=dict(MODEL);monitor=B.Monitor()
    args=dict(settings={'control':'samarbete','plan':True,'capacity_kwh':10},state={'soc_pct':50},
              profile={},now=datetime.now(timezone.utc),shadow=True)
    assert monitor.submit({'enabled':True,'allowed_intents':['auto'],'tariff_model':model},**args)
    model['buy_extra']=99
    assert monitor._queue.get_nowait()['tariff_model']==MODEL
    monitor=B.Monitor()
    assert monitor.submit({'enabled':True,'allowed_intents':['auto']},**args)
    assert monitor._queue.get_nowait()['tariff_model'] is None


@pytest.mark.parametrize('mode',['active','currency','vat'])
def test_active_planning_and_basis_mismatches_refused_before_db(monkeypatch,mode):
    import battery_plan,nordpool
    monkeypatch.setattr(nordpool,'cost_settings',lambda:{'currency':'EUR' if mode=='currency' else 'SEK'})
    monkeypatch.setattr(nordpool,'prices_include_vat',lambda:mode=='vat')
    with pytest.raises(ValueError):
        battery_plan.plan_from_db(None,datetime.now(timezone.utc),50,{}, {},{'auto'},
                                  comparison=mode!='active',tariff_model=MODEL)
