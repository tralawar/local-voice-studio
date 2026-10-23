import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DictationSession } from '../src/dictation.js';
function fixture(extra = {}) {
  const errors = [], track = { stopped: false, stop() { this.stopped = true; }, addEventListener() {} };
  class Recorder {
    static isTypeSupported() { return true; }
    constructor() { this.state = 'inactive'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; }
  }
  const session = new DictationSession({ mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track] }) },
    Recorder, transcribe: async () => ({}), onText() {}, onStatus() {}, onError: error => errors.push(error), ...extra });
  return { session, track, errors };
}
test('default timers retain the global receiver required by browser APIs', async () => {
  const savedSet = globalThis.setTimeout, savedClear = globalThis.clearTimeout, calls = [];
  globalThis.setTimeout = function (...args) { assert.equal(this, globalThis, 'Illegal invocation'); calls.push('set'); return 1; };
  globalThis.clearTimeout = function () { assert.equal(this, globalThis, 'Illegal invocation'); calls.push('clear'); };
  try {
    const h = fixture(); await h.session.start(); h.session.stop();
    assert.deepEqual(calls, ['set', 'clear']); assert.equal(h.track.stopped, true); assert.deepEqual(h.errors, []);
  } finally { globalThis.setTimeout = savedSet; globalThis.clearTimeout = savedClear; }
});
test('track release is guaranteed even if timer cleanup and recorder stop both throw', async () => {
  const h = fixture({ setTimer: () => 1, clearTimer: () => { throw new TypeError('synthetic cleanup failure'); } });
  await h.session.start(); h.session.recorder.stop = () => { throw new Error('synthetic recorder stop failure'); };
  h.session.stop();
  assert.equal(h.track.stopped, true); assert.equal(h.session.stream, null); assert.equal(h.session.recorder, null);
  assert.equal(h.errors.length, 1); assert.match(h.errors[0].message, /cleanup failure/);
});
