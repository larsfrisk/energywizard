const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ctx = vm.createContext({ window: {} });
vm.runInContext(fs.readFileSync('smartbox/static/liveflow.js', 'utf8'), ctx);
const flow = ctx.window.EWLiveFlow;

// Both overview consumers use this renderer: compact in EWApp, full-size on the web.
for (const compact of [true, false]) {
  for (const [w, state] of [[1500, 'Laddar'], [-1500, 'Laddar ur'], [0, 'Vilar']]) {
    for (const soc of [0, 57, 100, null]) {
      const battery = { key: 'batteri', label: 'Batteri', icon: '🔋', role: 'battery',
        w, active: w !== 0, detail: state + (soc == null ? '' : ` · ${soc} %`) };
      const html = flow.svg({ nodes: [battery] }, { compact });
      assert.match(html, new RegExp(`>${state.toLowerCase()}</text>`));
      assert.match(html, w === 0 ? />0<tspan/ : />1,5<tspan/);
      if (soc == null) assert.doesNotMatch(html, /\d+ %/);
      else assert.match(html, new RegExp(`y="${compact ? 47 : 26}"[^>]*>${soc} %</text>`));
      assert.doesNotMatch(html, /undefined|NaN|null/);
      assert.equal(html.includes('<animateMotion'), w !== 0);
    }
  }
  const solar = flow.svg({ nodes: [{ key: 'sol', label: 'Sol', role: 'source', w: 500,
    detail: 'Laddar · 57 %' }] }, { compact });
  assert.doesNotMatch(solar, /57 %/);
  for (const [w, state] of [[0, 'Laddar inte'], [3700, 'Laddar 3.7 kW']]) {
    for (const soc of [0, 72, 100, null]) {
      const html = flow.svg({nodes:[{key:'ev_nissan',label:'Nissan Leaf',icon:'🚗',role:'load',
        w,active:w>0,detail:state+(soc==null?'':` · ${soc} %`)}]}, {compact});
      if(soc==null) assert.doesNotMatch(html,/\d+ %/);
      else assert.match(html,new RegExp(`y="${compact?18:24}"[^>]*>${soc} %</text>`));
      assert.match(html,w===0?/>0<tspan/:/>3,7<tspan/);
      assert.match(html,w===0?/>laddar inte<\//:/>laddar<\//);
      assert.doesNotMatch(html,/NaN|undefined|null/);
    }
  }
}
console.log('Battery SoC, zero/full/unknown charge, power and operating states passed in both overview layouts');
