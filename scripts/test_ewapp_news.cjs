// Veckobrevets rad på Hem och arket (ewapp/static/app.js): bara ägaren ser den, bara när man inte anmält sig och inte klickat bort den.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const els = {};
const element = () => ({ innerHTML: '', style: { setProperty() {} }, classList: { add() {}, remove() {}, toggle() {} }, dataset: {},
  setAttribute() {}, removeAttribute() {}, addEventListener() {}, querySelectorAll: () => [], focus() {}, value: '' });
const get = (s) => (els[s] = els[s] || element());
const ctx = vm.createContext({ console, document: { documentElement: element(), body: element(), querySelector: get, getElementById: (i) => get('#' + i),
  querySelectorAll: () => [], addEventListener() {} },
  localStorage: { getItem: () => null, setItem() {} }, navigator: {}, location: { search: '' }, URLSearchParams,
  innerWidth: 400, innerHeight: 800, history: { replaceState() {} }, addEventListener() {},
  matchMedia: () => ({ matches: false }), setTimeout() {}, clearTimeout() {}, setInterval() {}, fetch: async () => ({ ok: true, json: async () => ({}) }) });
ctx.window = ctx;
ctx.I18N = { tr: (t) => t, lang: 'sv', languages: {} };      // i18n.js laddas före app.js i riktiga appen
vm.runInContext(fs.readFileSync('ewapp/static/app.js', 'utf8').replace(/\nstart\(\);\s*$/, ''), ctx);
const run = (code) => vm.runInContext(code, ctx);

// raden: bara ägare + ingen anmälan + inte bortklickad
run('ROLE = "owner"; VIEWAS = "";');
const line = (n, role) => run(`ROLE = ${JSON.stringify(role || 'owner')}; NEWS = ${JSON.stringify(n)}; newsLine()`);
assert.match(line({ status: 'none', dismissed: false }), /data-a="newsopen"/);
assert.match(line({ status: 'none', dismissed: false }), /data-a="newsx"/);
assert.equal(line({ status: 'none', dismissed: true }), '');
assert.equal(line({ status: 'pending', dismissed: false }), '');
assert.equal(line({ status: 'confirmed', dismissed: false }), '');
assert.equal(line(null), '');
for (const role of ['family', 'guest']) assert.equal(line({ status: 'none', dismissed: false }, role), '');

// arket: formulär, väntar, bekräftad; fel visas som text (och escapas)
const sheetHtml = (n, msg) => { els['#sheet'] = element(); run(`ROLE = "owner"; NEWS = ${JSON.stringify(n)}; newsSheet(${JSON.stringify(msg)})`); return els['#sheet'].innerHTML; };
let h = sheetHtml({ status: 'none' });
assert.match(h, /id="newsmail"/); assert.match(h, /data-a="newssub"/); assert.match(h, /Personuppgiftsansvarig/); assert.match(h, /telemetrin/);
h = sheetHtml({ status: 'pending', email: 'a<b>@x.se' });
assert.match(h, /a&lt;b&gt;@x\.se/); assert.match(h, /data-a="newscancel"/); assert.doesNotMatch(h, /id="newsmail"/);
h = sheetHtml({ status: 'confirmed', email: 'a@x.se' });
assert.match(h, /a@x\.se/); assert.match(h, /Avsluta prenumerationen/);
h = sheetHtml({ status: 'none' }, 'Skriv en <giltig> adress');
assert.match(h, /&lt;giltig&gt;/);
console.log('veckobrevets rad och ark: roller, lägen, escaping OK');

// fliken Nyheter: finns för alla roller, visar utgåvorna (escapade), tomt läge, anmälningsraden bara för ägaren
for (const role of ['owner', 'family', 'guest']) assert.ok(run('TABS')[role].includes('nyheter'), 'fliken saknas för ' + role);
assert.equal(run('TABNAME.nyheter'), 'Nyheter'); assert.ok(run('ICON.nyheter').startsWith('<svg'));
const nyh = (role, nf, news) => run(`ROLE = ${JSON.stringify(role)}; VIEWAS = ""; NF = ${JSON.stringify(nf)}; NEWS = ${JSON.stringify(news)}; pageNyheter()`);
const issues = [{ id: '2026-w48', period: '17–24 november 2026', versions: '1.2.153–1.2.178', items: [['Testa <b>ditt</b> system', 'Text & mer']] }];
let n = nyh('guest', issues, null);
assert.match(n, /Vecka/); assert.match(n, /48/); assert.match(n, /17–24 november 2026/); assert.match(n, /Testa &lt;b&gt;ditt&lt;\/b&gt; system/); assert.match(n, /Text &amp; mer/); assert.match(n, /1\.2\.153–1\.2\.178/);
assert.doesNotMatch(n, /newsopen/);                                                       // gäster/familj ser inte anmälan
assert.doesNotMatch(nyh('family', issues, { status: 'none' }), /newsopen/);
assert.match(nyh('owner', issues, { status: 'none' }), /data-a="newsopen"/);              // ägaren som inte anmält sig får raden överst
assert.doesNotMatch(nyh('owner', issues, { status: 'confirmed', email: 'a@x.se' }), /newsopen/);
assert.match(nyh('guest', [], null), /Inga veckobrev ännu/);
assert.match(nyh('guest', null, null), /Laddar/);
console.log('fliken Nyheter: alla roller, innehåll, tomt läge, anmälan bara för ägaren OK');
