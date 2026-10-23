import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { DraftSaveQueue } from '../src/draft.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const requests = [];
  const draft = { text: 'Synthetic edit', revision: 0 };
  const saver = new DraftSaveQueue({ getDraft: () => draft,
    acknowledgeRevision: revision => { draft.revision = revision; },
    persist: snapshot => new Promise((resolve, reject) => requests.push({ snapshot, resolve, reject })) });
  return { draft, saver, requests };
}
test('pending save keeps actual unload warning and beacon active until acknowledgment', async () => {
  const { draft, saver, requests } = fixture();
  const handlers = {}, beacons = [];
  const source = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  const unload = source.slice(source.indexOf("window.addEventListener('pagehide'"), source.indexOf('init().then(storagePanel)'));
  vm.runInNewContext(unload, { window: { addEventListener: (event, handler) => { handlers[event] = handler; } },
    draftSaver: saver, draft, voiceFormDirty: false, Blob, stopDictation() {}, navigator: { sendBeacon: (...args) => beacons.push(args) } });
  saver.markEdited(); const save = saver.save(); await tick();
  assert.equal(saver.pending, true); assert.equal(saver.unsaved, true);
  let warned = false;
  handlers.beforeunload({ preventDefault() { warned = true; } }); handlers.pagehide();
  assert.equal(warned, true); assert.equal(beacons.length, 1);
  assert.equal(await beacons[0][1].text(), JSON.stringify(draft));
  requests[0].resolve({ revision: 1 }); await save;
  assert.equal(saver.unsaved, false); assert.equal(saver.pending, false);
  warned = false; handlers.beforeunload({ preventDefault() { warned = true; } }); handlers.pagehide();
  assert.equal(warned, false); assert.equal(beacons.length, 1);
});
test('older acknowledgment cannot clear a newer edit; queued save uses updated revision', async () => {
  const { draft, saver, requests } = fixture();
  saver.markEdited(); const first = saver.save(); await tick();
  draft.text = 'Newer synthetic edit'; saver.markEdited(); const second = saver.save();
  requests[0].resolve({ revision: 1 }); await first; await tick();
  assert.equal(saver.unsaved, true);
  assert.deepEqual(requests[1].snapshot, { text: 'Newer synthetic edit', revision: 1 });
  requests[1].resolve({ revision: 2 }); await second;
  assert.equal(saver.unsaved, false); assert.equal(draft.revision, 2);
});
test('failed save remains unsaved and a retry can acknowledge it', async () => {
  const { draft, saver, requests } = fixture();
  saver.markEdited(); const first = saver.save(); const failure = assert.rejects(first, /storage failed/); await tick();
  requests[0].reject(new Error('storage failed')); await failure;
  assert.equal(saver.unsaved, true); assert.equal(saver.pending, false); assert.equal(draft.revision, 0);
  const retry = saver.save(); await tick(); requests[1].resolve({ revision: 1 }); await retry;
  assert.equal(saver.unsaved, false); assert.equal(saver.error, null);
});
test('unsaved voice reference text retains the actual unload warning', () => {
  const handlers = {}, source = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  const unload = source.slice(source.indexOf("window.addEventListener('pagehide'"), source.indexOf('init().then(storagePanel)'));
  vm.runInNewContext(unload, { window: { addEventListener: (event, handler) => { handlers[event] = handler; } },
    draftSaver: { unsaved: false }, voiceFormDirty: true, stopDictation() {}, navigator: {}, Blob });
  let warned = false; handlers.beforeunload({ preventDefault() { warned = true; } }); assert.equal(warned, true);
});
