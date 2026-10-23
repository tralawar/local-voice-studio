import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { DictationController } from '../src/dictation.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
test('actual Edit callback invalidates pending reference dictation before replacing a preset', async () => {
  let timer, finish; const nodes = {}, track = { stopped: false, enabled: true, stop() { this.stopped = true; }, addEventListener() {} };
  const $ = id => nodes[id] ?? (nodes[id] = { value: '', focus() {} });
  $('voice-id').value = 'A'; $('voice-transcript').value = 'Synthetic preset A';
  class Recorder {
    static isTypeSupported() { return true; }
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(['synthetic']) }); queueMicrotask(() => this.onstop()); }
  }
  const controller = new DictationController({ Recorder, mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track] }) },
    transcribe: () => new Promise(resolve => { finish = resolve; }),
    onText: (_, text) => { $('voice-transcript').value += ' ' + text; }, onStatus() {}, onError() {},
    setTimer: callback => { timer = callback; }, clearTimer() {} });
  await controller.toggle('voice'); timer(); await tick();
  const source = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  const prefix = "actions.append(button('Edit', "; const start = source.indexOf(prefix) + prefix.length;
  const end = source.indexOf('}));', start) + 1;
  vm.runInNewContext('(' + source.slice(start, end) + ')()', { $, voiceFormDirty: true,
    voice: { id: 'B', name: 'Synthetic B', transcript: 'Synthetic preset B' },
    dictation: controller, stopDictation: () => controller.stop() });
  finish({ text: 'late words from A', elapsed: .1 }); await tick();
  assert.equal($('voice-id').value, 'B'); assert.equal($('voice-transcript').value, 'Synthetic preset B');
  assert.equal(track.stopped, true); assert.equal(controller.stream, null);
});
