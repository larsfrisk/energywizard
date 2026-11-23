from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import hot_water_reservations as R
from test_hot_water_runtime import house

T=datetime(2026,11,16,10,tzinfo=timezone.utc)


def configuration():
    h=house();h['battery']={'hot_water_reservations':{'enabled':True,'background_kw':.5}}
    return h


def test_partial_quarters_preserve_exact_modelled_energy_and_do_not_add_mixed_history():
    h=configuration();h['heat_pump']['hot_water_control']['comfort_policy']['electrical_power_kw']=2.5
    runtime=SimpleNamespace(controller=SimpleNamespace(state={'phase':'planned','start':T.timestamp()+300,
        'end':T.timestamp()+1500,'deadline':T.timestamp()+1800}))
    reservation=R.window(runtime,h,T.timestamp())
    slots=[{'t':T+timedelta(minutes=15*i),'load_kw':8,'ev_kw':1,'buy':1,'sell':0} for i in range(3)]
    original=deepcopy(slots)
    rows=R.apply(slots,reservation,{},T.timestamp())
    assert sum(r['hot_water_kw']*.25 for r in rows)==pytest.approx(2.5/3)
    assert all(r['load_kw']==pytest.approx(.5+r['hot_water_kw']) and r['ev_kw']==1 for r in rows)
    assert slots==original
    with pytest.raises(ValueError):R.apply(rows,reservation,{},T.timestamp())


def test_cancelled_release_and_runtime_bounds_remove_only_future_reservations():
    h=configuration();cycle={'phase':'active','start':T.timestamp()-300,'end':T.timestamp()+3000,
        'deadline':T.timestamp()+4000,'attempted_at':T.timestamp()-300,'max_runtime_s':900}
    rt=SimpleNamespace(controller=SimpleNamespace(state=cycle))
    reservation=R.window(rt,h,T.timestamp())
    assert reservation['window']['end']==T.timestamp()+600
    before=R.identity(reservation)
    assert R.identity(R.window(rt,h,T.timestamp()+10))==before
    cycle['phase']='complete'
    assert R.window(rt,h,T.timestamp())['window'] is None
    assert R.identity(R.window(rt,h,T.timestamp()))!=before
    h['heat_pump']['hot_water_control']['enabled']=False
    assert R.window(rt,h,T.timestamp()) is None


def test_known_off_profile_takes_precedence_over_explicit_fallback():
    s={'t':T,'load_kw':20,'ev_kw':2}
    rows=R.apply([s],{'background_kw':.5,'window':None},{(T.weekday(),T.hour):.8},T.timestamp())
    assert rows[0]['load_kw']==.8 and rows[0]['ev_kw']==2
    assert R.configuration({}) is None
    with pytest.raises(ValueError):R.configuration({'battery':{'hot_water_reservations':{'enabled':True}}})


def test_fresh_boost_state_is_independent_of_temperature_and_unknown_is_not_off():
    b={'start_value':3,'release_value':0}
    p={'metadata':{'divisor':1},'value':{'integerValue':0}}
    resolve=lambda pts,binding:('id',p)
    for raw,expected in [(0,False),(3,True),(2,None)]:
        p['value']['integerValue']=raw
        r=R.boost_fields({}, {'hot_water_boost':b},resolve,lambda p:p['value']['integerValue'],T.isoformat())
        assert r['hot_water_boost_active'] is expected
    assert R.boost_fields({}, {},resolve,lambda p:0,T.isoformat())['hot_water_boost_active'] is None


def test_actual_history_query_excludes_unknown_stale_active_and_future_samples(db,smartbox):
    from sqlalchemy import create_engine
    import os
    # Seed three distinct Mondays with 30 fresh, explicitly off samples each.
    db.execute('TRUNCATE sensor_log')
    for week in (1,2,3):
        day=T-timedelta(days=7*week)
        for minute in range(30):
            stamp=day+timedelta(minutes=minute)
            db.execute('INSERT INTO sensor_log(timestamp,house_consumption_w,ev_power_kw,hot_water_boost_active,hot_water_boost_sample_at) VALUES (%s,%s,%s,%s,%s)',
                       (stamp,1500,.5,False,stamp.timestamp()))
            for offset,(flag,at) in enumerate([(None,stamp.timestamp()),(True,stamp.timestamp()),
                                             (False,stamp.timestamp()-1000),(False,stamp.timestamp()+1000)],1):
                db.execute('INSERT INTO sensor_log(timestamp,house_consumption_w,hot_water_boost_active,hot_water_boost_sample_at) VALUES (%s,%s,%s,%s)',
                           (stamp+timedelta(seconds=offset),30000,flag,at))
    engine=create_engine(f"postgresql+psycopg://postgres:test@localhost/{os.environ['POSTGRES_DB']}")
    profile=R.off_profile(engine,T)
    assert profile[(T.weekday(),11)]==1  # Stockholm UTC+1 in November.
    engine.dispose()


def test_active_database_plan_stores_reservation_and_replays_effective_limits(db,smartbox,monkeypatch,tmp_path):
    import os
    import battery_plan,ew_settings,ha_solar_forecast,learning,nordpool,plan_snapshot,weather
    from sqlalchemy import create_engine
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    monkeypatch.setattr(ew_settings,'PATH',str(tmp_path/'settings.json'))
    ew_settings.update(battery_normal_max_soc=90,battery_discharge_buffer_soc=2)
    monkeypatch.setattr(learning,'predict_base_load',lambda *a:8)
    monkeypatch.setattr(ha_solar_forecast,'power_at',lambda *a:None)
    monkeypatch.setattr(weather,'get_weather_at',lambda *a:(0,0,0,0))
    monkeypatch.setattr(weather,'get_smart_solar_w',lambda *a,**k:0)
    monkeypatch.setattr(nordpool,'full_buy_cost',lambda p,t:p)
    monkeypatch.setattr(nordpool,'full_sell_income',lambda p:0)
    snapshots=[]
    def capture(slots,params,result,made_at,quality=None):
        snapshots.append(plan_snapshot.build(slots,params,result,made_at,quality=quality))
    monkeypatch.setattr(plan_snapshot,'capture',capture)
    db.execute('TRUNCATE elpriser')
    db.execute('TRUNCATE sensor_log')     # det föregående testet lämnar rader runt "nu"; utan detta smittar den inlärda baslasten av sig beroende på klockslag
    db.execute('DROP TABLE IF EXISTS battery_plan_forecast')
    for i in range(8):db.execute('INSERT INTO elpriser VALUES (%s,%s)',(now+timedelta(minutes=i*15),1))
    engine=create_engine(f"postgresql+psycopg://postgres:test@localhost/{os.environ['POSTGRES_DB']}")
    cfg={'capacity_kwh':10,'reserve_soc':10,'max_soc':100,'max_power_w':3000,'efficiency':1}
    reservation={'background_kw':.5,'window':{'start':now.timestamp()+300,'end':now.timestamp()+1500,'power_kw':2.5}}
    result=battery_plan.plan_from_db(engine,now,50,cfg,{}, {'auto','charge','hold','discharge'},hot_water=reservation)
    assert result['rows'] and result['input_quality']['hot_water']['source']=='scheduled_boost_model'
    snap=snapshots[0];assert plan_snapshot.replay(snap)['matches']
    assert snap['inputs']['params']['reserve_kwh']==1.2 and snap['inputs']['params']['max_kwh']==9
    slots=snap['inputs']['slots'];assert sum(s['hot_water_kw']*.25 for s in slots)==pytest.approx(2.5/3)
    assert all(s['load_kw']==pytest.approx(.5+s['hot_water_kw']) for s in slots)
    rows=db.execute('SELECT load_kw FROM battery_plan_forecast ORDER BY t_slot').fetchall()
    assert [float(r[0]) for r in rows]==pytest.approx([s['load_kw'] for s in slots],abs=.0001)
    engine.dispose()
