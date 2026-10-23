import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DictationController } from '../src/dictation.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture({ empty = false, permissionError, transcribe = async () => ({ text: 'new words', elapsed: .2 }) } = {}) {
  const fields = { script: 'Existing script', voice: 'Existing reference words' }, errors = [], requests = [], tracks = [];
  let timer;
  class Recorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm'); }
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm;codecs=opus'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(empty ? [] : ['synthetic']) }); queueMicrotask(() => this.onstop()); }
  }
  const controller = new DictationController({ Recorder,
    mediaDevices: { getUserMedia: async () => {
      if (permissionError) throw permissionError;
      const track = { enabled: true, stopped: false, stop() { this.stopped = true; }, addEventListener() {} };
      tracks.push(track); return { getTracks: () => [track] };
    } },
    transcribe: audio => { requests.push(audio.type); return transcribe(audio); },
    onText: (target, text) => { fields[target] += ' ' + text; },
    onStatus() {}, onError: (target, message) => errors.push({ target, message }),
    setTimer: callback => { timer = callback; }, clearTimer() {}
  });
  return { controller, fields, errors, requests, tracks, fireTimer: () => timer() };
}
test('reference dictation appends only to the reference field and preserves existing script', async () => {
  const h = fixture(); await h.controller.toggle('voice'); h.controller.stop(true); await tick();
  assert.equal(h.fields.voice, 'Existing reference words new words'); assert.equal(h.fields.script, 'Existing script');
  assert.deepEqual(h.requests, ['audio/webm;codecs=opus']); assert.equal(h.tracks[0].stopped, true);
});
test('blocked microphone permission gives an actionable error without changing either field', async () => {
  const h = fixture({ permissionError: Object.assign(new Error('denied'), { name: 'NotAllowedError' }) });
  await h.controller.toggle('voice'); assert.match(h.errors[0].message, /Microphone access was blocked/);
  assert.equal(h.errors[0].target, 'voice'); assert.equal(h.fields.voice, 'Existing reference words'); assert.deepEqual(h.requests, []);
});
test('empty browser recording is rejected locally without an API request or text loss', async () => {
  const h = fixture({ empty: true }); await h.controller.toggle('script'); h.controller.stop(true); await tick();
  assert.match(h.errors[0].message, /No audio was captured/); assert.deepEqual(h.requests, []); assert.equal(h.fields.script, 'Existing script');
});
test('switching destination drops a late response and never starts a concurrent microphone', async () => {
  let finish; const h = fixture({ transcribe: () => new Promise(resolve => { finish = resolve; }) });
  await h.controller.toggle('voice'); h.fireTimer(); await tick();
  await assert.rejects(h.controller.toggle('script'), /still processing/);
  finish({ text: 'late words', elapsed: .3 }); await tick();
  assert.equal(h.fields.voice, 'Existing reference words'); assert.equal(h.fields.script, 'Existing script'); assert.equal(h.tracks.length, 1);
});
test('local transcription failure releases microphone and leaves both input fields intact', async () => {
  const h = fixture({ transcribe: async () => { throw new Error('The local dictation service could not be reached.'); } });
  await h.controller.toggle('voice'); h.controller.stop(true); await tick();
  assert.match(h.errors[0].message, /could not be reached/); assert.equal(h.tracks[0].stopped, true);
  assert.equal(h.fields.voice, 'Existing reference words'); assert.equal(h.fields.script, 'Existing script');
});
