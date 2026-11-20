// "Ladda nu" syns i flödesrutan: en bil som laddar dyrt på ett manuellt kommando ska inte se ut som ett misstag.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ctx = vm.createContext({ window: {} });
vm.runInContext(fs.readFileSync('smartbox/static/liveflow.js', 'utf8'), ctx);
const flow = ctx.window.EWLiveFlow;
const ev = (over) => ({ key: 'ev_nissan', label: 'Nissan Leaf', icon: '🚗', role: 'load', w: 4400, active: true,
  detail: 'Laddar 4.4 kW · 64 %', ...over });
for (const compact of [true, false]) {
  const manual = flow.svg({ nodes: [ev({ manual: true })] }, { compact });
  assert.match(manual, />ladda nu<\//);
  assert.doesNotMatch(manual, />laddar<\//);
  assert.match(manual, /64 %/);                                                 // laddnivån visas som förut
  const manualWaiting = flow.svg({ nodes: [ev({ manual: true, w: 0, active: false, detail: 'Laddar inte · 64 %' })] }, { compact });
  assert.match(manualWaiting, />ladda nu<\//);                                  // kommandot är givet även innan strömmen kommit
  const auto = flow.svg({ nodes: [ev({})] }, { compact });
  assert.match(auto, />laddar<\//);
  assert.doesNotMatch(auto, /ladda nu/);
  const idle = flow.svg({ nodes: [ev({ w: 0, active: false, detail: 'Laddar inte · 64 %' })] }, { compact });
  assert.match(idle, />laddar inte<\//);
  assert.doesNotMatch(manual + manualWaiting + auto + idle, /NaN|undefined|null/);
}
console.log('Manual "Ladda nu" label passed in both overview layouts');
