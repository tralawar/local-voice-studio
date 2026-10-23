import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OutputControls, exportMessage } from '../src/outputs.js';

test('picker cancellation preserves the chosen folder and never submits a filesystem path', async () => {
  const calls = []; const changes = [];
  const controls = new OutputControls({ api: async (...args) => { calls.push(args); return args[0] === 'output-folder' ? { folder: 'synthetic selected folder', action_token: 'secret' } : { cancelled: true }; }, onPreferences: p => changes.push(p) });
  await controls.load(); await controls.choose();
  assert.equal(controls.preferences.folder, 'synthetic selected folder'); assert.equal(changes.length, 1);
  assert.deepEqual(calls[1], ['output-folder/choose', {}, false, { 'X-Output-Token': 'secret' }]);
});

test('Save as is one action, serializes native pickers and releases busy UI after failure', async () => {
  let fail; const busy = [];
  const controls = new OutputControls({ api: () => new Promise((_, reject) => { fail = reject; }), onPreferences() {}, onBusy: value => busy.push(value) });
  controls.preferences = { action_token: 'token' };
  const action = controls.saveAs('synthetic');
  await assert.rejects(controls.choose(), /Finish or cancel/);
  fail(new Error('disk disconnected'));
  await assert.rejects(action, /disk disconnected/);
  assert.deepEqual(busy, [true, false]); assert.equal(controls.busy, false);
});

test('external errors explain that history is safe; pending is distinct from saved', () => {
  assert.match(exportMessage({ export: { status: 'pending' } }), /Saving a WAV/);
  assert.match(exportMessage({ export: { status: 'error', error: 'Disk full. Audio is safe in history.' } }), /safe in history/);
  assert.match(exportMessage({ export: { status: 'saved', folder: 'selected', filename: 'take.wav' } }), /selected.*take.wav/);
});
