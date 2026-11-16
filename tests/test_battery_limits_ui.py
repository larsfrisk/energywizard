from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.skipif(shutil.which('node') is None,reason='Node.js required')
def test_settings_controls_save_and_restore_rejected_values_in_translated_card():
    root=Path(__file__).resolve().parents[1]
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('webdashboard/static/app.js','utf8');
const elements=Object.fromEntries(['batplancard','batstyle','batstyledesc','batexport','batnormalmax','batreservebuffer'].map(k=>[k,{}]));
const sent=[];let reject=false;
const ctx={document:{getElementById:k=>elements[k],querySelectorAll:()=>[]},
  BAT_STYLES:{balanced:['Balanced','desc']},esc:x=>x,toast:()=>{},
  api:async()=>({has_battery:true,style:'balanced',styles:['balanced'],allow_export:false,normal_max_soc:90,discharge_buffer_soc:2}),
  postJSON:async(path,body)=>{if(reject)throw Error('synthetic');sent.push(body);return body;}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('async function mountBatteryPlanSettings('),source.indexOf('function mountLangSelect(')),ctx);
(async()=>{
 await ctx.mountBatteryPlanSettings();assert.equal(elements.batnormalmax.value,90);assert.equal(elements.batreservebuffer.value,2);
 elements.batnormalmax.value='85';await elements.batnormalmax.onchange();assert.equal(sent[0].normal_max_soc,85);
 elements.batreservebuffer.value='';await elements.batreservebuffer.onchange();assert.equal(elements.batreservebuffer.value,2);assert.equal(sent.length,1);
 reject=true;elements.batnormalmax.value='101';await elements.batnormalmax.onchange();assert.equal(elements.batnormalmax.value,85);
 for(const lang of ['en','cs']){
  const dict=JSON.parse(fs.readFileSync('smartbox/i18n/'+lang+'.json','utf8'));
  for(const key of ['Normal laddgräns (%)','Marginal över reservnivån (%)','Ogiltiga batterigränser'])assert(dict[key]);
 }
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node','-e',script],cwd=root,check=True,capture_output=True,text=True)
