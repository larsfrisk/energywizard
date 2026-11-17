const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

// Minimal DOM surface used by the updater; track moves of existing elements,
// since moving/replacing a live SVG animation is the regression under test.
class Node {
  constructor(name, value = null) {
    this.nodeName = this.localName = name; this.nodeType = name === '#text' ? 3 : 1;
    this.nodeValue = value; this.childNodes = []; this.attrs = new Map(); this.moves = 0;
  }
  get attributes() { return Array.from(this.attrs, ([name, value]) => ({name, value})); }
  get firstChild() { return this.childNodes[0] || null; }
  get firstElementChild() { return this.childNodes.find(n => n.nodeType === 1) || null; }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(n => n.textContent).join(''); }
  set textContent(value) { if (this.nodeType === 3) this.nodeValue = value; else this.replaceChildren(new Node('#text', value)); }
  set innerHTML(value) { this.replaceChildren(...parse(value).childNodes); }
  querySelectorAll(selector) {
    const matches = n => selector === '#batinv' ? n.getAttribute('id') === 'batinv'
      : (n.getAttribute('class') || '').split(' ').includes(selector.slice(1).split('[')[0])
        && (!selector.includes('[data-page]') || n.hasAttribute('data-page'));
    const result = [];
    for (const n of this.childNodes) if (n.nodeType === 1) {
      if (matches(n)) result.push(n);
      result.push(...n.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] || null; }
  getAttribute(name) { return this.attrs.get(name) ?? null; }
  hasAttribute(name) { return this.attrs.has(name); }
  setAttribute(name, value) { this.attrs.set(name, value); }
  removeAttribute(name) { this.attrs.delete(name); }
  remove() { if (this.parentNode) this.parentNode.childNodes.splice(this.parentNode.childNodes.indexOf(this), 1); this.parentNode = null; }
  insertBefore(node, cursor) {
    if (node.parentNode) { node.moves++; node.remove(); }
    this.childNodes.splice(cursor ? this.childNodes.indexOf(cursor) : this.childNodes.length, 0, node); node.parentNode = this;
  }
  replaceChildren(...nodes) { for (const n of [...this.childNodes]) n.remove(); for (const n of nodes) this.insertBefore(n, null); }
  cloneNode(deep) {
    const copy = new Node(this.nodeName, this.nodeValue); copy.attrs = new Map(this.attrs);
    if (deep) for (const n of this.childNodes) copy.insertBefore(n.cloneNode(true), null);
    return copy;
  }
}
function parse(svg) {
  const root = new Node('fragment'), stack = [root];
  for (const token of svg.match(/<[^>]+>|[^<]+/g) || []) {
    if (token.startsWith('</')) { stack.pop(); continue; }
    let node;
    if (token.startsWith('<')) {
      node = new Node(token.match(/^<([\w]+)/)[1]);
      for (const m of token.matchAll(/([\w:-]+)="([^"]*)"/g)) node.setAttribute(m[1], m[2]);
    } else node = new Node('#text', token);
    stack.at(-1).insertBefore(node, null);
    if (node.nodeType === 1 && !token.endsWith('/>')) stack.push(node);
  }
  return root;
}
const ctx = vm.createContext({window: {}, document: {createElement() {
  return {set innerHTML(value) { this.content = parse(value); }};
}}});
vm.runInContext(fs.readFileSync('smartbox/static/liveflow.js', 'utf8'), ctx);
const flow = ctx.window.EWLiveFlow;
const source = (key, w, role = 'source') => ({key, w, role, label:key, icon:'', active: Math.abs(w) > 50});
const byKey = (svg, key) => svg.childNodes.find(n => n.getAttribute('data-flow-key') === key);
for (const compact of [false, true]) {
  const container = new Node('div'), opts = {compact};
  const initial = {nodes: [source('sol', 500), source('nat', 800, 'grid'), source('hus', 1300)]};
  flow.update(container, initial, opts);
  const svg = container.firstElementChild, dot = byKey(svg, 'dot-nat-1'), motion = dot.firstChild;
  const solarDot = byKey(svg, 'dot-sol-0'), card = byKey(svg, 'card-nat');
  const begin = motion.getAttribute('begin');
  flow.update(container, initial, opts);
  assert.equal(container.firstElementChild, svg);
  assert.equal(byKey(svg, 'dot-nat-1'), dot);
  assert.equal(dot.firstChild, motion);
  assert.equal(dot.moves, 0);
  // New readings, reversed grid direction and an extra solar dot keep existing
  // animations attached; text, speed and direction still change.
  flow.update(container, {nodes: [source('sol', 4500), source('nat', -600, 'grid'), source('hus', 3900)]}, opts);
  assert.equal(byKey(svg, 'dot-nat-1'), dot);
  assert.equal(byKey(svg, 'dot-sol-0'), solarDot);
  assert.equal(byKey(svg, 'card-nat'), card);
  assert.equal(motion.getAttribute('begin'), begin);
  assert.equal(motion.getAttribute('keyPoints'), '1;0');
  assert.equal(motion.getAttribute('dur'), '2.99s');
  assert.ok(byKey(svg, 'dot-sol-2'));
  assert.equal(dot.moves, 0);
  const texts = n => n.nodeType === 3 ? n.nodeValue : n.childNodes.map(texts).join('');
  assert.match(texts(card), /600/);
  assert.match(texts(card), /säljer/);
  flow.update(container, {nodes: [source('sol', 0), source('nat', -600, 'grid')]}, opts);
  assert.equal(byKey(svg, 'dot-sol-0'), undefined);
  assert.equal(byKey(svg, 'dot-nat-1'), dot);
  assert.equal(dot.moves, 0);
  // Removed equipment disappears without restarting another device's dots.
  flow.update(container, {nodes: [source('nat', -600, 'grid')]}, opts);
  assert.equal(byKey(svg, 'card-sol'), undefined);
  assert.equal(byKey(svg, 'dot-nat-1'), dot);
  assert.equal(dot.moves, 0);
  ctx.window.I18N = {tr: s => s === 'säljer' ? 'selling' : s};
  flow.update(container, {nodes: [source('nat', -600, 'grid')]}, opts);
  assert.match(texts(byKey(svg, 'card-nat')), /selling/);
  assert.equal(byKey(svg, 'dot-nat-1'), dot);
  delete ctx.window.I18N;
  ctx.window.matchMedia = ctx.matchMedia = () => ({matches:true});
  flow.update(container, {nodes: [source('nat', -600, 'grid')]}, opts);
  assert.equal(byKey(svg, 'dot-nat-1'), undefined);
  assert.ok(byKey(svg, 'card-nat'));
  delete ctx.window.matchMedia; delete ctx.matchMedia;
}

// Exercise the real overview polling integration as well as the SVG updater.
(async () => {
  const slot = new Node('div'); let poll, reading = 500, requests = 0, navigate = 0;
  Object.assign(ctx, {EWLiveFlow: flow, currentPage: 'oversikt', PAGES: [{id:'sol'}],
    api: async () => { requests++; return {ok:true, ts:String(requests), why:{sol:'Producing'}, nodes:[source('sol', reading)]}; },
    esc: s => String(s ?? ''), clearInterval(){}, setInterval(fn){poll=fn;return 1;},
    openPage(){navigate++;}});
  ctx.document.getElementById = () => slot;
  const app = fs.readFileSync('webdashboard/static/app.js', 'utf8');
  const start = app.indexOf('async function mountFlow(');
  vm.runInContext('let flowTimer=null;\n'+app.slice(start, app.indexOf('// ---------- Dygnet', start)), ctx);
  await ctx.mountFlow('flow');
  const card = slot.firstChild, graphic = slot.querySelector('.flow-graphic'), svg = graphic.firstElementChild;
  const dot = byKey(svg, 'dot-sol-0'), motion = dot.firstChild;
  const notes = slot.querySelector('.flow-notes').firstChild;
  reading = 800;
  poll(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(slot.firstChild, card);
  assert.equal(graphic.firstElementChild, svg);
  assert.equal(byKey(svg, 'dot-sol-0'), dot);
  assert.equal(dot.firstChild, motion);
  assert.equal(dot.moves, 0);
  assert.equal(slot.querySelector('.flow-notes').firstChild, notes);
  assert.equal(slot.querySelector('.flow-time').textContent, '2');
  // Rebinding replaces the handler instead of stacking listeners each poll.
  byKey(svg, 'card-sol').dataset = {page:'sol'};
  byKey(svg, 'card-sol').onclick();
  assert.equal(navigate, 1);
  assert.match(byKey(svg, 'card-sol').textContent, /800/);
  console.log('Polling preserves card/SVG/animations/unchanged notes and updates readings and navigation');
})().catch(e => { console.error(e); process.exitCode = 1; });
