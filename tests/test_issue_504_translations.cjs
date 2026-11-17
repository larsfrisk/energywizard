const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function check(lang) {
  const dict=JSON.parse(fs.readFileSync(`smartbox/i18n/${lang}.json`,'utf8'));
  const ctx={window:{},document:{readyState:'loading',addEventListener(){}},
    localStorage:{getItem:()=>lang},fetch:async url=>({ok:true,json:async()=>url.endsWith('config')?{languages:{sv:'Svenska',en:'English',cs:'Čeština'}}:dict})};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('smartbox/i18n/i18n.js','utf8'),ctx);
  await ctx.window.I18N.ready;const tr=ctx.window.I18N.tr;
  for(const [source,expected] of Object.entries(dict)) {
    if(source.startsWith('_'))continue;
    assert.ok(expected,`${lang}: empty translation: ${source}`);
    assert.equal(tr(source),expected,`${lang}: unreachable catalog entry: ${source}`);
  }
  // Use the actual rendered heading from #504, including its icon.
  const web=fs.readFileSync('webdashboard/static/app.js','utf8');
  const heading=web.match(/<h2>(☀️ Ordning för solöverskott)<\/h2>/)[1];
  assert.equal(tr(heading),lang==='en'?'☀️ Order for solar surplus':'☀️ Pořadí pro solární přebytek');
  assert.equal(tr('  '+heading+'\n'),'  '+dict[heading]+'\n');
  const messages=[
    'Vattnet är kritiskt svalt (37.9°C). Tvingar varmvatten oavsett elpris och effekttak!',
    'Byter läge till CHEAP, låser i 60 minuter.',
    'Minuspris. Netto: -500W. Fel: 500. Justering: -0.25%. Ny gräns: 85%.',
    'Laddar enligt schema. Husets säkring tillåter 14A. Sätter Auto <1>: 0A, Moje auto: 14A.',
    'Batteriet laddar ur och säljer',
    'Batteriet är på reservnivån (11 % ≤ 12 %) - sparas till strömavbrott. Konfigurerad standby använder en liten urladdning och stoppar även solladdning.',
  ];
  for(const source of messages) {
    const result=tr(source);
    assert.notEqual(result,source);
    assert.doesNotMatch(result,/Vattnet|Tvingar|Byter|låser|Minuspris|Ny gräns|Husets|Sätter|Batteriet|använder|stoppar|solladdning/);
    if(source.includes('Auto <1>'))assert.ok(result.includes('Auto <1>: 0A, Moje auto: 14A'));
    if(source.includes('-500W'))assert.ok(result.includes('-500W')&&result.includes('-0.25%'));
  }
  // A multiline notification without a whole-message key still translates
  // line by line and preserves its line endings and user-provided names.
  const notification=tr('🚗 Bilen laddar\r\nLaddningen av Auto <1> har startat med 3.7 kW.');
  assert.doesNotMatch(notification,/Bilen|Laddningen/);
  assert.match(notification,/\r\n/);
  assert.match(notification,/Auto <1>/);
}
(async()=>{for(const lang of ['en','cs'])await check(lang);console.log('All catalog entries reachable; rendered headings, decisions and notifications translate in English and Czech');})().catch(e=>{console.error(e);process.exitCode=1;});
