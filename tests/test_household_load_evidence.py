"""Direct AC total-load capture, private logging, export and causal evaluation."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
import subprocess
import sys

import psycopg
import pytest
from sqlalchemy import create_engine,text
import energy_source_evidence as E
from energy_source_export import export
from household_load_evidence import CONTRACT,reconstruct

T=datetime(2026,11,14,12,tzinfo=timezone.utc)
HOUSE={'energy_source_evidence':{'enabled':True,'boundary':'ac_household','target':'household_total',
       'household':{'entity_id':'sensor.test_load','positive':'consumption'}}}


def capture(at=T,value=2000,unit='W'):
    cache={'sensor.test_load':{'state':str(value),'last_reported':at.isoformat(),
           'attributes':{'unit_of_measurement':unit,'device_class':'power'}}}
    return E.capture(HOUSE,cache,{},now=at.timestamp())


def quarter():return [capture(T+timedelta(minutes=i)) for i in range(16)]


def test_direct_capture_needs_no_components_and_preserves_units_dates_privacy():
    sample=capture(value=2,unit='kW')
    assert sample['schema']==2 and sample['load_w']==2000
    assert sample['load_sample_at']==T.timestamp() and sample['load_basis']=='ha_report'
    assert not sample['physical_verified'] and sample['target']=='household_total'
    cleaned=E.log_value(sample|{'entity_id':'private','credentials':'secret'})
    assert 'private' not in json.dumps(cleaned) and 'secret' not in json.dumps(cleaned)
    assert cleaned==sample and 'grid_w' not in cleaned and 'hot_water_power_w' not in cleaned
    assert capture(value=0)['load_w']==0
    assert capture(value=-1)['load_w'] is None
    assert E.capture({}, {},{},now=T.timestamp()) is None


@pytest.mark.parametrize('change',[{'load_w':True},{'load_w':-1},{'load_w':float('inf')},
    {'target':'hot_water_excluded'},{'physical_verified':True},{'load_basis':'guessed'}])
def test_bad_schema_two_fields_are_refused(change):
    assert E.log_value(capture()|change) is None


def test_exact_energy_and_no_hidden_exclusions():
    samples=quarter();original=deepcopy(samples);result=reconstruct(samples,CONTRACT)
    assert result['rows']==[{'t':int(T.timestamp()),'kw':2,'coverage':1.,'covered_energy_kwh':.5}]
    assert result['baseline_contract']=='household_total' and result['excluded_loads']==[]
    assert not result['adoption_ready'] and samples==original
    with pytest.raises(ValueError):reconstruct(samples,CONTRACT|{'excluded_loads':['hot_water']})
    with pytest.raises(ValueError):reconstruct([samples[0]|{'controlled_w':[]}],CONTRACT)


@pytest.mark.parametrize('change',[{'load_sample_at':None},{'load_sample_at':T.timestamp()-300},
    {'load_sample_at':T.timestamp()+1},{'load_w':None},{'load_basis':'unknown'}])
def test_invalid_middle_evidence_stays_a_gap_without_bridging(change):
    samples=quarter();samples[8].update(change)
    result=reconstruct(samples,CONTRACT,max_gap_s=300)
    assert not result['rows']
    assert result['report']['rejected_intervals']['invalid_endpoint']==2


def test_source_expiry_mapping_change_and_receipt_acceptance():
    samples=quarter()
    for sample in samples:sample['load_sample_at']-=40
    assert not reconstruct(samples,CONTRACT)['rows']
    assert reconstruct(samples,CONTRACT)['report']['rejected_intervals']['source_expires_within_interval']==15
    samples=quarter()
    for sample in samples[8:]:sample['source_context']='f'*64
    result=reconstruct(samples,CONTRACT)
    assert not result['rows'] and result['report']['rejected_intervals']['mixed_source_context_quarters']==1
    samples=quarter()
    for sample in samples:sample['load_basis']='local_receipt'
    assert not reconstruct(samples,CONTRACT)['rows']
    assert reconstruct(samples,CONTRACT,allow_receipt=True)['rows'][0]['kw']==2


def test_actual_private_log_export_reconstruct_and_wrong_target_gaps(db,monkeypatch):
    import logger
    @contextmanager
    def connection():yield db
    monkeypatch.setattr(logger,'get_db',connection);monkeypatch.setattr(logger,'_bool_columns',set())
    logger.init_log_db()
    class Clock:
        at=T
        @classmethod
        def now(cls,zone):return cls.at.astimezone(zone)
    monkeypatch.setattr(logger,'datetime',Clock)
    for i in range(16):
        Clock.at=T+timedelta(minutes=i)
        logger.log_status(*([None]*20),pump={},energy_evidence=capture(Clock.at)|{'credentials':'secret'})
    engine=create_engine('postgresql+psycopg://',creator=lambda:psycopg.connect(db.info.dsn,password=os.environ['POSTGRES_PASSWORD']))
    try:
        with engine.connect() as conn:
            result=export(conn,T,T+timedelta(minutes=15),target='household_total')
            assert conn.execute(text('SHOW transaction_read_only')).scalar()=='on'
        assert result['contract']==CONTRACT and 'secret' not in json.dumps(result)
        assert reconstruct(result['samples'],result['contract'])['rows'][0]['kw']==2
        with engine.connect() as conn:wrong=export(conn,T,T+timedelta(minutes=15))
        assert wrong['export_report']['invalid_evidence_rows']==16
        assert all(s['evidence_missing'] for s in wrong['samples'])
    finally:
        engine.dispose()
        db.execute('DELETE FROM sensor_log WHERE timestamp >= %s AND timestamp <= %s',(T,T+timedelta(minutes=15)))


def test_export_target_refused_before_database_access():
    with pytest.raises(ValueError):export(object(),T,T+timedelta(minutes=15),target='unknown')


def test_gaps_duplicates_and_final_sample_are_not_filled():
    samples=quarter();samples[8]['timestamp']=samples[7]['timestamp']
    with pytest.raises(ValueError):reconstruct(samples,CONTRACT)
    samples=quarter();del samples[4:8]
    assert not reconstruct(samples,CONTRACT)['rows']
    assert not reconstruct(quarter()[:-1],CONTRACT,min_coverage=1)['rows']


def test_dst_repeated_hours_remain_physical_quarters():
    from zoneinfo import ZoneInfo
    start=datetime(2026,10,25,tzinfo=timezone.utc)
    samples=[capture((start+timedelta(minutes=i)).astimezone(ZoneInfo('Europe/Stockholm'))) for i in range(121)]
    result=reconstruct(samples,CONTRACT)
    assert len(result['rows'])==8 and len({r['t'] for r in result['rows']})==8


def test_eight_day_direct_capture_cli_forecast_evaluation(tmp_path):
    start=T.replace(hour=0);samples=[capture(start+timedelta(minutes=i)) for i in range(8*1440+1)]
    path=tmp_path/'direct.json';path.write_text(json.dumps({'contract':CONTRACT,'samples':samples}))
    result=subprocess.run([sys.executable,'scripts/evaluate_household_forecast.py',str(path),
        '--source-dated','--split',(start+timedelta(days=7)).isoformat(),'--candidate-method','recent_trend'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout)
    assert data['evaluation_quarters']==96 and data['coverage']['accepted_quarters']==768
    assert data['input_contract']['baseline_contract']=='household_total' and data['input_contract']['excluded_loads']==[]
    assert not data['adoption_ready'] and data['economic_evaluation'] is None
