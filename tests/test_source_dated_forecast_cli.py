"""Raw dated captures must be reconstructed, never trusted as precomputed rows."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from hot_water_residual import CHANNELS,CONTRACT

START=datetime(2026,10,1,tzinfo=timezone.utc)
SCRIPT='scripts/evaluate_household_forecast.py'


@pytest.fixture(scope='module')
def capture():
    rows=[]
    for i in range(8*1440+1):
        at=START+timedelta(minutes=i)
        row={'timestamp':at.isoformat()}
        for (watts,stamp,basis),value in zip(CHANNELS,(2500,0,0,500)):
            row.update({watts:value,stamp:at.timestamp(),basis:'ha_report'})
        rows.append(row)
    return {'contract':CONTRACT,'samples':rows}


def run(path,*extra):
    return subprocess.run([sys.executable,SCRIPT,str(path),'--split',
        (START+timedelta(days=7)).isoformat(),'--timezone','UTC','--source-dated',*extra],
        text=True,capture_output=True)


@pytest.mark.parametrize('method',['median_blend','recent_trend'])
def test_raw_source_capture_runs_actual_reconstruction_and_error_evaluation(tmp_path,capture,method):
    path=tmp_path/'private.json';raw=json.dumps(capture);path.write_text(raw)
    result=run(path,'--candidate-method',method)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout)
    assert data['candidate_method']==method and data['training_quarters']==672
    assert data['evaluation_quarters']==96 and data['coverage']['accepted_quarters']==768
    assert data['predictions'][0]['actual_kw']==2
    assert data['input_contract']=={'baseline_contract':'hot_water_excluded',
        'excluded_loads':['hot_water'],'measurement_qualification':'not_established'}
    assert not data['adoption_ready'] and data['economic_evaluation'] is None
    assert path.read_text()==raw and list(tmp_path.iterdir())==[path]


def test_missing_source_dates_cannot_be_filled_from_log_time_or_fake_summary(tmp_path,capture):
    data=json.loads(json.dumps(capture))
    for row in data['samples']:del row['grid_sample_at']
    data['rows']=[{'t':START.timestamp(),'kw':2}]*768
    data['report']={'accepted_quarters':768}
    path=tmp_path/'private.json';path.write_text(json.dumps(data))
    result=run(path)
    assert result.returncode!=0 and not result.stdout
    assert 'Invalid or insufficient' in result.stderr


def test_receipt_dates_require_explicit_offline_acceptance(tmp_path,capture):
    data=json.loads(json.dumps(capture))
    for row in data['samples']:
        for _,_,basis in CHANNELS:row[basis]='local_receipt'
    path=tmp_path/'private.json';path.write_text(json.dumps(data))
    assert run(path).returncode!=0
    result=run(path,'--allow-receipt')
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['coverage']['receipt_evidence_accepted'] is True
    assert report['input_contract']['measurement_qualification']=='not_established'
    assert not report['adoption_ready']


def test_unaligned_planner_snapshot_scoring_is_rejected_before_read(tmp_path):
    result=run(tmp_path/'missing.json','--planner-snapshot',str(tmp_path/'missing-plan.json'))
    assert result.returncode!=0 and not result.stdout
    assert 'separately aligned controlled-load' in result.stderr


def test_bad_contract_errors_do_not_publish_extra_input_fields(tmp_path):
    path=tmp_path/'private.json';path.write_text(json.dumps({'contract':{'secret':'never-print'},'samples':[]}))
    result=run(path)
    assert result.returncode!=0 and 'never-print' not in result.stderr and not result.stdout
