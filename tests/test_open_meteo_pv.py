"""Documented irradiance timing, energy, gaps, caching and comparison isolation."""
from datetime import datetime, timedelta, timezone
import json
from threading import Event

import pytest

import open_meteo_pv as P
from ha_solar_forecast import average_w

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
CONFIG = dict(enabled=True,source='open_meteo',latitude=50,longitude=10,tilt_deg=30,azimuth_deg=0,kwp=5,derate=.8)


def payload(values=(500,0,None), start=NOW):
    return {'hourly_units':{'time':'unixtime','global_tilted_irradiance':'W/m²'},
            'hourly':{'time':[int((start+timedelta(hours=i+1)).timestamp()) for i in range(len(values))],
                      'global_tilted_irradiance':list(values)}}


def test_preceding_hour_means_conserve_energy_and_keep_missing_distinct_from_zero():
    rows = P.parse(payload(),P.configuration(CONFIG))
    assert rows[0] == (NOW,NOW+timedelta(hours=1),2000)
    assert sum(average_w(rows,NOW+timedelta(minutes=15*i),NOW+timedelta(minutes=15*(i+1)))*.25/1000 for i in range(4)) == 2
    assert average_w(rows,NOW+timedelta(hours=1),NOW+timedelta(hours=2)) == 0
    assert average_w(rows,NOW+timedelta(hours=2),NOW+timedelta(hours=3)) is None


@pytest.mark.parametrize('change',[{'latitude':91},{'longitude':-181},{'tilt_deg':-1},{'azimuth_deg':181},
    {'kwp':0},{'derate':0},{'derate':1.1},{'derate':True},{'latitude':float('nan')},{'source':'other'}])
def test_invalid_explicit_geometry_never_fetches(change):
    calls=[]
    source=P.Forecast(lambda c:calls.append(c),clock=lambda:NOW.timestamp())
    assert source.snapshot(CONFIG|change)['state']=='invalid_config' and not calls


@pytest.mark.parametrize('kind',['units','duplicate','reverse','nonhour','length'])
def test_ambiguous_series_rejected(kind):
    data=payload()
    if kind=='units':data['hourly_units']['global_tilted_irradiance']='kWh'
    elif kind=='duplicate':data['hourly']['time'][1]=data['hourly']['time'][0]
    elif kind=='reverse':data['hourly']['time'].reverse()
    elif kind=='nonhour':data['hourly']['time'][0]+=60
    else:data['hourly']['time'].pop()
    with pytest.raises(ValueError):P.parse(data,P.configuration(CONFIG))


def test_hourly_cache_expires_and_failed_refresh_never_reuses_old_forecast():
    clock=[NOW.timestamp()];calls=[]
    def reader(config):
        calls.append(config)
        if len(calls)>1:raise RuntimeError('private endpoint details')
        return payload()
    source=P.Forecast(reader,clock=lambda:clock[0])
    assert source.snapshot(CONFIG)['state']=='partial'
    clock[0]+=60
    assert source.snapshot(CONFIG)['periods'] and len(calls)==1
    clock[0]+=3600
    result=source.snapshot(CONFIG)
    assert result['state']=='unavailable' and not result['periods']
    assert 'private' not in str(result)


def test_fetch_uses_fixed_endpoint_utc_and_bounded_response(monkeypatch):
    calls=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield json.dumps(payload()).encode()
    def get(url,**kwargs):calls.append((url,kwargs));return Response()
    monkeypatch.setattr(P.requests,'get',get)
    assert P.fetch(P.configuration(CONFIG))['hourly']
    assert calls[0][0]==P.URL
    assert calls[0][1]['params']['timezone']=='UTC' and calls[0][1]['params']['azimuth']==0
    assert calls[0][1]['allow_redirects'] is False
    monkeypatch.setattr(Response,'iter_content',lambda self,size:iter([b'x'*2_000_001]))
    with pytest.raises(ValueError):P.fetch(P.configuration(CONFIG))


def test_worker_only_uses_explicit_comparison_model(monkeypatch):
    import battery_shadow as B, shadow
    monkeypatch.setattr(shadow,'active',lambda:True)
    monkeypatch.setattr(B.time,'time',lambda:NOW.timestamp())
    captured=[];done=Event()
    monitor=B.Monitor(lambda e:(captured.append(e),done.set()))
    monitor._pv=P.Forecast(lambda c:payload(),clock=lambda:NOW.timestamp())
    settings=dict(control='samarbete',plan=True,capacity_kwh=10)
    assert monitor.submit({'enabled':True,'allowed_intents':['auto'],'pv_model':CONFIG|{'token':'private'}},settings,{'soc_pct':50},{},now=NOW,shadow=True)
    assert done.wait(2)
    assert captured[0]['pv_forecast']['state']=='partial'
    assert 'token' not in captured[0]['pv_model']


def test_real_candidate_uses_pv_periods_keeps_gaps_and_rejects_active_override(db, monkeypatch, tmp_path):
    import battery_plan, ew_settings, ha_solar_forecast, learning, nordpool, plan_snapshot, weather
    from sqlalchemy import create_engine
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    db.execute('TRUNCATE elpriser')
    for i in range(8):db.execute('INSERT INTO elpriser VALUES(%s,1)',(now+timedelta(minutes=15*i),))
    monkeypatch.setattr(ew_settings,'PATH',str(tmp_path/'settings.json'))
    monkeypatch.setattr(ha_solar_forecast,'power_at',lambda *args:None)
    monkeypatch.setattr(learning,'predict_base_load',lambda *args:1)
    monkeypatch.setattr(weather,'get_weather_at',lambda *args:(0,0,0,0))
    monkeypatch.setattr(weather,'get_smart_solar_w',lambda *args,**kwargs:500)
    monkeypatch.setattr(nordpool,'full_buy_cost',lambda price,*args:price)
    monkeypatch.setattr(nordpool,'full_sell_income',lambda price:0)
    snapshots=[]
    def capture(*args,**kwargs):
        snap=plan_snapshot.build(*args,**kwargs);snapshots.append(snap);return snap['plan_id']
    monkeypatch.setattr(plan_snapshot,'capture',capture)
    forecast={'state':'partial','periods':P.parse(payload((500,None),now),P.configuration(CONFIG)), 'fetched_at':now.timestamp()}
    engine=create_engine('postgresql+psycopg://postgres:test@localhost/smartbox_test')
    settings=dict(capacity_kwh=10,reserve_soc=20,max_soc=90,max_power_w=1000)
    try:
        with pytest.raises(ValueError):battery_plan.plan_from_db(engine,now,50,settings,{}, {'auto'},pv_forecast=forecast)
        result=battery_plan.plan_from_db(engine,now,50,settings,{}, {'auto'},comparison=True,pv_forecast=forecast)
        assert [s['solar_kw'] for s in snapshots[0]['inputs']['slots']]==[2]*4+[.5]*4
        assert result['input_quality']['pv_model']['coverage']==.5
        assert result['input_quality']['solar']=={'source':'mixed','coverage':.5}
        assert 'latitude' not in plan_snapshot.canonical(snapshots[0])
        assert plan_snapshot.replay(snapshots[0])['matches'] and not result['control_ready']
    finally:engine.dispose()
