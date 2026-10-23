// Incremental, complete audio segments. This is not a streaming ASR protocol.
export class DictationSession {
  constructor({ mediaDevices, Recorder, transcribe, onText, onStatus, onError,
    setTimer = (...args) => globalThis.setTimeout(...args),
    clearTimer = (...args) => globalThis.clearTimeout(...args) }) {
    Object.assign(this, { mediaDevices, Recorder, transcribe, onText, onStatus, onError, setTimer, clearTimer });
    this.epoch = 0; this.stream = null; this.recorder = null; this.pending = false; this.starting = false;
  }
  async start() {
    if (this.pending) throw new Error('The previous audio segment is still processing.');
    if (this.starting || this.stream) throw new Error('A microphone request is already active.');
    const epoch = ++this.epoch;
    this.starting = true;
    let stream;
    try { stream = await this.mediaDevices.getUserMedia({ audio: true }); }
    finally { this.starting = false; }
    if (epoch !== this.epoch) { stream.getTracks().forEach(track => track.stop()); return; }
    this.stream = stream;
    stream.getTracks().forEach(track => track.addEventListener('ended', () => this.stop()));
    this.onStatus('Listening locally · 4-second segments', true);
    try { this.segment(epoch); }
    catch (error) { this.stop(); throw error; }
  }
  stop(flushFinal = false) {
    if (!flushFinal) this.epoch++;
    let cleanupError;
    try { this.clearTimer(this.timer); } catch (error) { cleanupError = error; }
    try { if (this.recorder?.state === 'recording') this.recorder.stop(); }
    catch (error) { cleanupError ||= error; }
    finally {
      this.recorder = null;
      for (const track of this.stream?.getTracks() || []) {
        try { track.stop(); } catch (error) { cleanupError ||= error; }
      }
      this.stream = null;
    }
    this.onStatus('Mic is off', false);
    if (cleanupError) this.onError(cleanupError);
  }
  segment(epoch) {
    if (!this.stream || epoch !== this.epoch) return;
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => this.Recorder.isTypeSupported(type));
    const recorder = new this.Recorder(this.stream, mimeType ? { mimeType } : {}), parts = [];
    this.recorder = recorder;
    recorder.ondataavailable = event => { if (event.data.size) parts.push(event.data); };
    recorder.onerror = () => { this.stop(); this.onError(new Error('Recording failed. Microphone released.')); };
    recorder.onstop = async () => {
      if (epoch !== this.epoch) return;
      this.pending = true;
      this.stream?.getTracks().forEach(track => track.enabled = false);
      this.onStatus(this.stream ? 'Transcribing locally · mic paused' : 'Finishing local transcription · mic off', Boolean(this.stream));
      try {
        const audio = new Blob(parts, { type: recorder.mimeType || mimeType });
        if (!audio.size) throw new Error('No audio was captured. Record for a moment before pressing Stop, then try again.');
        const result = await this.transcribe(audio);
        if (epoch !== this.epoch) return;
        if (result.text) this.onText(result.text);
        this.onStatus(result.text ? `${this.stream ? 'Listening' : 'Mic is off'} · last segment ${result.elapsed}s`
          : `${this.stream ? 'Listening' : 'Mic is off'} · no speech detected in the last segment`, Boolean(this.stream));
      } catch (error) { this.stop(); this.onError(error); }
      finally { this.pending = false; }
      if (epoch === this.epoch && this.stream) {
        this.stream.getTracks().forEach(track => track.enabled = true);
        try { this.segment(epoch); } catch (error) { this.stop(); this.onError(error); }
      }
    };
    recorder.start();
    this.timer = this.setTimer(() => { if (recorder.state === 'recording') recorder.stop(); }, 4000);
  }
}

export function dictationErrorMessage(error) {
  const messages = {
    NotAllowedError: 'Microphone access was blocked. Allow it for this localhost page in your browser, then press Dictate again.',
    SecurityError: 'Microphone access needs a secure page. Open this workspace on localhost or 127.0.0.1.',
    NotFoundError: 'No microphone was found. Connect one and select it in your browser before trying again.',
    NotReadableError: 'The microphone is busy or unavailable. Check your audio device and operating-system microphone settings.',
    AbortError: 'Microphone capture was interrupted. Your existing text is unchanged; try Dictate again.',
    OverconstrainedError: 'This microphone does not support the requested capture settings. Select another input device.'
  };
  return messages[error?.name] || error?.message || 'Dictation failed. Your existing text is unchanged.';
}

// One microphone session shared by all text fields. Each session captures its
// destination, so late results can never spill into another editor.
export class DictationController {
  constructor({ onText, onStatus, onError, ...options }) {
    Object.assign(this, { onText, onStatus, onError, options });
    this.session = null; this.target = null;
  }
  get stream() { return this.session?.stream; }
  stop(flushFinal = false) { this.session?.stop(flushFinal); }
  async toggle(target) {
    if (this.session?.starting) throw new Error('Waiting for microphone permission. Resolve the browser prompt before trying again.');
    if (this.stream) {
      const same = this.target === target;
      this.stop(same);
      if (same) return;
    }
    if (this.session?.pending) throw new Error('The previous audio segment is still processing. Wait a moment, then try Dictate again.');
    this.target = target;
    this.session = new DictationSession({ ...this.options,
      onText: text => this.onText(target, text),
      onStatus: (message, active) => this.onStatus(target, message, active),
      onError: error => this.onError(target, dictationErrorMessage(error))
    });
    try { await this.session.start(); }
    catch (error) { this.onError(target, dictationErrorMessage(error)); }
  }
}
