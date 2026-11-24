const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const previewHtml = fs.readFileSync('ha-cards/preview.html', 'utf8');
const scriptStart = previewHtml.indexOf('<script>');
assert.notEqual(scriptStart, -1);
const preview = previewHtml.slice(scriptStart + '<script>'.length, previewHtml.lastIndexOf('</script>'));
for (const [query, tag] of [
  ['', 'energywizard-house-card'],
  ['?card=house', 'energywizard-house-card'],
  ['?card=heat', 'energywizard-heat-card'],
  ['?card=car', 'energywizard-car-card'],
  ['?card=unsupported', 'energywizard-house-card'],
]) {
  const card = { setConfig() {} };
  vm.runInNewContext(preview, {
    URLSearchParams,
    location: { search: query },
    document: {
      body: {},
      createElement(name) {
        assert.equal(name, tag);
        return card;
      },
      getElementById() {
        return { appendChild(element) { assert.equal(element, card); } };
      },
    },
  });
  assert.ok(card.hass.states['sensor.energywizard_kort']);
}

const source=fs.readFileSync('ewapp/static/app.js','utf8');
const start=source.indexOf('function spaReadySheet()');
const end=source.indexOf('\n}',start)+2;
const sheet={};let rendered='';
const ctx={H:{spa:{}},Date,esc:s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
 f1:n=>String(n),sheet:s=>{rendered=s;},$:s=>s==='#sheet'?sheet:s==='#swd'?{value:'"><img src=x onerror=alert(1)>'}:{value:'07:00'}};   // datumfältet får en ondskefull sträng, tidsfältet en giltig tid
vm.createContext(ctx);
// normTid (24-timmarsklockslag) används av arket för tidsfältet
const ns=source.indexOf('function normTid(');vm.runInContext(source.slice(ns,source.indexOf('\n}',ns)+2),ctx);
vm.runInContext(source.slice(start,end),ctx);ctx.spaReadySheet();
(async()=>{await sheet.onclick({target:{closest:()=>({dataset:{v:'t+'}})}});
assert.match(rendered,/value="&quot;&gt;&lt;img src"/);
assert.doesNotMatch(rendered,/<img/);console.log('Spa sheet preserves input as escaped attribute text');})().catch(e=>{console.error(e);process.exitCode=1;});
