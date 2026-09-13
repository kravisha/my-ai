const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../backend/console/index.html'), 'utf8');
const code = html.slice(html.indexOf('let studioBuilt='), html.indexOf('function renderStudio()'));
function setup() {
  const pending = [];
  const elements = {'studio-cam': {value: 'camera'}, 'studio-video': {srcObject: null}, 'studio-note': {}};
  const context = vm.createContext({S: {studioActive: false}, $: id => elements[id],
    navigator: {mediaDevices: {getUserMedia: () => new Promise((resolve, reject) => pending.push({resolve, reject}))}}});
  vm.runInContext(code + ';studioEnumerate=async()=>{};', context);
  return {pending, elements, context, run: code => vm.runInContext(code, context)};
}
function stream() {
  const track = {stopped: false, label: 'Test camera', stop() {this.stopped=true;},
    getSettings() {return {};}, addEventListener(event, callback) {this[event]=callback;}};
  return {track, getTracks: () => [track], getVideoTracks: () => [track]};
}
(async () => {
  let h = setup(), s = stream();
  let start = h.run('studioStart()');
  h.run('studioStop()');
  h.pending[0].resolve(s); await start;
  assert.equal(s.track.stopped, true, 'Stop must release a camera granted after cancellation');
  assert.equal(h.elements['studio-video'].srcObject, null);
  assert.equal(h.context.S.studioActive, false);

  h = setup(); const older=stream(), newer=stream();
  const a=h.run('studioStart()'), b=h.run('studioStart()');
  h.pending[1].resolve(newer); await b;
  h.pending[0].resolve(older); await a;
  assert.equal(older.track.stopped, true);
  assert.equal(h.elements['studio-video'].srcObject, newer, 'Newest request owns preview');
  newer.track.ended();
  assert.equal(h.context.S.studioActive, false);
  assert.equal(h.elements['studio-video'].srcObject, null);
  assert.match(h.elements['studio-note'].textContent, /disconnected/);

  h = setup(); s=stream();
  const rejected=h.run('studioStart()'), accepted=h.run('studioStart()');
  h.pending[1].resolve(s); await accepted;
  h.pending[0].reject(new Error('Old request failed')); await rejected;
  assert.match(h.elements['studio-note'].textContent, /Local preview/);
  h.run('studioStop()'); assert.equal(s.track.stopped, true);
  console.log('Studio camera lifecycle: cancellation, replacement, disconnect and stale rejection passed');
})().catch(error => {console.error(error); process.exitCode=1;});
