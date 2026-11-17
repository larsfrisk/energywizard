const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('ewapp/static/app.js','utf8');
const start=source.indexOf('function spaReadySheet()');
const end=source.indexOf('\n}',start)+2;
const sheet={};let rendered='';
const ctx={H:{spa:{}},Date,esc:s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
 f1:n=>String(n),sheet:s=>{rendered=s;},$:s=>s==='#sheet'?sheet:{value:'"><img src=x onerror=alert(1)>'}};
vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);ctx.spaReadySheet();
(async()=>{await sheet.onclick({target:{closest:()=>({dataset:{v:'t+'}})}});
assert.match(rendered,/value="&quot;&gt;&lt;img src=x onerror=alert\(1\)&gt;"/);
assert.doesNotMatch(rendered,/<img/);console.log('Spa sheet preserves input as escaped attribute text');})().catch(e=>{console.error(e);process.exitCode=1;});
