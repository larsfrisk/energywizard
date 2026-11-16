"""Scoped live controls must never be described as a completely passive house."""
from pathlib import Path
import shutil
import subprocess
import asyncio
from unittest.mock import Mock

import pytest
from test_hot_water_owner_status import web
from test_hot_water_runtime import house


def test_shadow_api_exposes_only_code_owned_scope_names(web, monkeypatch):
    cfg=house()
    cfg['heat_pump']['hot_water_control'].update(driver='nibe_local',live_control_confirmed=True)
    monkeypatch.setattr(web.house_config,'load_house_config',lambda path:cfg)
    monkeypatch.setattr(web.ENGINE,'connect',Mock(side_effect=OSError('private endpoint')))
    result=asyncio.run(web.shadow_get())
    assert result['scoped_controls']==['hot_water']
    assert 'never-publish' not in str(result) and 'private' not in str(result)
    monkeypatch.setattr(web.house_config,'load_house_config',Mock(side_effect=OSError('private')))
    assert asyncio.run(web.shadow_get())['scoped_controls'] is None


@pytest.mark.skipif(shutil.which('node') is None,reason='Node.js required')
def test_scope_notice_translates_for_english_and_czech_without_false_passive_claim():
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('webdashboard/static/app.js','utf8');
const start=source.indexOf('function shadowScopeText('),end=source.indexOf('async function mountShadow()',start);
const c={};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
for(const lang of ['en','cs']){
 const d=JSON.parse(fs.readFileSync('smartbox/i18n/'+lang+'.json','utf8'));
 const passive=c.shadowScopeText({scoped_controls:[]});
 const mixed=c.shadowScopeText({scoped_controls:['hot_water','battery']});
 assert.notEqual(passive,mixed);assert(d[passive]);assert(d[mixed]);
 assert.equal(c.shadowScopeText({scoped_controls:null}),mixed);
 assert.equal(c.shadowScopeText({}),passive);
}
'''
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
