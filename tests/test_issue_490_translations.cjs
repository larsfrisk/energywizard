// Exercise the actual browser translator and notification text nodes in all languages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
async function run(lang) {
  const catalog = lang === 'sv' ? {} : JSON.parse(fs.readFileSync(`smartbox/i18n/${lang}.json`, 'utf8'));
  let start;
  const parent = {tagName:'DIV', closest:()=>null};
  const text = {nodeType:3, parentElement:parent, textContent:'Huset drar ~4.5 kW, varav **2.0 kW är OFÖRKLARAT** (inte elbil, värmepump eller spa).\n\nKolla t.ex. ugn, bastu, tvätt/tork, laddare eller element.'};
  const body = {nodeType:1, tagName:'BODY', hasAttribute:()=>false, getAttribute:()=>null, firstChild:text};
  const context = {window:{}, document:{readyState:'loading',body,documentElement:{},addEventListener:(_,fn)=>{start=fn;}}, localStorage:{getItem:()=>lang}, fetch:async url=>({ok:true,json:async()=>url.endsWith('config')?{languages:{sv:'Svenska',en:'English',cs:'Čeština'}}:catalog}), MutationObserver:class{observe(){}}, navigator:{}, console};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('smartbox/i18n/i18n.js','utf8'),context);
  await context.window.I18N.ready;
  const tr=context.window.I18N.tr;
  start();
  if(lang==='en') assert.equal(tr('Bra tider att köra disk eller tvätt:\n  00:00–06:00 (0.28 €/kWh)'), 'Good times to run the dishwasher or washing machine:\n  00:00–06:00 (0.28 €/kWh)');
  const spa='Nästa badtid tis 16:00 – Värmer nu på billiga timmar så att badet är varmt i tid.';
  const expected={en:'Next bathing time Tue 16:00 – Heating now during cheap hours so the hot tub is warm in time.',cs:'Další koupání út 16:00 – Ohřev nyní během levných hodin, aby byla vířivka včas teplá.'};
  assert.equal(tr(spa),expected[lang]||spa);
  for(const day of ['mån','tis','ons','tor','fre','lör','sön']) {
    const source=`Nästa badtid ${day} 08:15 – Badet vilar på eco-golvet tills det är dags att värma.`;
    if(lang==='sv') assert.equal(tr(source),source);
    else assert.doesNotMatch(tr(source),/Nästa|Badet|vilar/);
  }
  if(lang==='sv') assert.match(text.textContent,/OFÖRKLARAT/);
  else {
    assert.doesNotMatch(text.textContent,/OFÖRKLARAT|Kolla|värmepump/);
    assert.match(text.textContent,/4.5/);
    assert.match(text.textContent,/\n\n/);
    const message='🚗 Bilen laddar\r\nLaddningen av Nissan <Leaf> har startat med 3.7 kW.';
    assert.doesNotMatch(tr(message),/Bilen|Laddningen/);
    assert.match(tr(message),/Nissan <Leaf>/);
    assert.match(tr(message),/\r\n/);
    const phases='⚡ Fasströmmar (nät): L1 4.1 A · L2 2.0 A · L3 3.2 A. Nätimport 3.5 kW mot känt 1.0 kW → minst 2.5 kW oförklarat enligt fasströmmarna.';
    assert.doesNotMatch(tr(phases),/Fasströmmar|Nätimport|oförklarat|känt/);
    assert.equal(tr('External device: <unknown>\n123'), 'External device: <unknown>\n123');
  }
}
(async()=>{for(const lang of ['sv','en','cs']) await run(lang);console.log('Issue 490 browser translation regression checks passed');})().catch(e=>{console.error(e);process.exitCode=1;});
