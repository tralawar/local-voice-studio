import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DictationSession } from '../src/dictation.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(transcribe = async () => ({ text: 'Synthetic text', elapsed: .2 })) {
  const track = { stopped: false, enabled: true, stop() { this.stopped = true; }, addEventListener() {} };
  const stream = { getTracks: () => [track] };
  let recorder, timer; const text = [];
  class Recorder {
    static isTypeSupported() { return true; }
    constructor() { recorder = this; this.state = 'inactive'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(['synthetic']) }); queueMicrotask(() => this.onstop()); }
  }
  const session = new DictationSession({ mediaDevices: { getUserMedia: async () => stream }, Recorder, transcribe,
    onText: value => text.push(value), onStatus() {}, onError: error => { throw error; },
    setTimer: callback => { timer = callback; }, clearTimer() {} });
  return { session, track, text, getRecorder: () => recorder, fireTimer: () => timer() };
}
test('user stop flushes final segment and releases tracks', async () => {
  const h = harness(); await h.session.start(); h.session.stop(true); await tick();
  assert.equal(h.track.stopped, true); assert.deepEqual(h.text, ['Synthetic text']); assert.equal(h.session.stream, null);
});
test('navigation stop drops late results and cannot restart recording', async () => {
  let finish; const h = harness(() => new Promise(resolve => { finish = resolve; }));
  await h.session.start(); h.fireTimer(); await tick();
  assert.equal(h.track.enabled, false); h.session.stop(); finish({ text: 'late', elapsed: 1 }); await tick();
  assert.deepEqual(h.text, []); assert.equal(h.track.stopped, true); assert.equal(h.getRecorder().state, 'inactive');
});
test('permission resolving after page hide releases acquired stream', async () => {
  let resolvePermission;
  const h = harness(); h.session.mediaDevices.getUserMedia = () => new Promise(resolve => { resolvePermission = resolve; });
  const starting = h.session.start(); h.session.stop(); resolvePermission({ getTracks: () => [h.track] }); await starting;
  assert.equal(h.track.stopped, true); assert.equal(h.session.stream, null);
});
