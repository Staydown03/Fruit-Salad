// Offline dashboard behavior checks: node tests/dashboard.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'dashboard.py'), 'utf8');
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes = new Map();
const document = {
  getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, { style: {}, src: '', innerHTML: '', textContent: '', replaceWith(candidate) { nodes.set(id, candidate); } });
    return nodes.get(id);
  },
  querySelectorAll() { return []; },
};
let data = { fruit_running: true, fruit: { running: true, seek: { ok: true, last_poll: Date.now()/1000 - 700 } }, recording: {}, counts: {} };
const images = [];
class Image {
  constructor() { this.style = {}; images.push(this); }
  replaceWith(candidate) { nodes.set(this.id, candidate); }
}
const context = vm.createContext({ document, Image, Date, Math, String, Object, encodeURIComponent,
  fetch: async () => ({ json: async () => data }), setInterval() {} });
vm.runInContext(script, context);
(async () => {
  await context.tick();
  assert.match(nodes.get('alerts').innerHTML, /FIRST polling is overdue/);
  assert.match(nodes.get('now').innerHTML, /class="bad"/);
  assert.equal(images.length, 0);
  data.matches = [{ level: 'Qualification', number: 1, red: [], blue: [], clip_db: null, clip_audio_status: 'pending' }];
  await context.tick();
  assert.match(nodes.get('rows').innerHTML, /Pending/);
  data.matches[0].clip_audio_status = 'check failed - will retry';
  await context.tick();
  assert.match(nodes.get('rows').innerHTML, /Check failed; will retry/);
  data.recording = { thumb_at: 123, thumb_time: 'first' };
  await context.tick();
  assert.equal(images.length, 1);
  images[0].onload();
  const previous = nodes.get('thumb').src;
  await context.tick();
  assert.equal(images.length, 1, 'unchanged images should not be downloaded every tick');
  data.recording = { thumb_at: 124, thumb_time: 'second' };
  await context.tick();
  images[1].onerror();
  assert.equal(nodes.get('thumb').src, previous, 'failed download must retain the last visible image');
  await context.tick();
  images[2].onload();
  assert.notEqual(nodes.get('thumb').src, previous);
  assert.match(nodes.get('thumbcap').textContent, /Last successful preview/);
  console.log('Dashboard checks passed: stale FIRST warning, image caching, failed-image retention and recovery.');
})().catch(error => { console.error(error); process.exitCode = 1; });
