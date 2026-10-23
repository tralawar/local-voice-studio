import './style.css';
import { LocalLinter } from 'harper.js';
import { binary } from 'harper.js/binary';
import { formatScript, wordCount, maskSpeechTags } from './text.js';
import { DictationController, dictationErrorMessage } from './dictation.js';
import { DraftSaveQueue } from './draft.js';
import { OutputControls, exportMessage } from './outputs.js';

const $ = id => document.getElementById(id);
const linter = new LocalLinter({ binary });
let draft, voices = [], history = [], activeJob = null, tab = 'studio';
let saveTimer, polling, undoText = null, status;
let dictation;
let voiceFormDirty = false;
let currentOutputId = null;
const exportWatches = new Set();
const outputControls = new OutputControls({
  api: (...args) => api(...args),
  onPreferences: preferences => {
    $('output-folder-name').textContent = preferences.folder ? preferences.folder.split(/[\\/]/).filter(Boolean).pop() || preferences.folder : 'History only';
    $('output-folder-name').title = preferences.folder || 'Choose a folder to automatically save future WAV takes.';
    $('output-folder-name').setAttribute('aria-label', preferences.folder ? `Automatic WAV output folder: ${preferences.folder}` : 'History only. No automatic output folder selected.');
    $('output-folder-details').textContent = preferences.folder || 'No automatic output folder selected. History keeps every take.';
    $('choose-output-folder').textContent = preferences.folder ? 'Change folder…' : 'Choose folder…';
    $('clear-output-folder').hidden = !preferences.folder;
    $('choose-output-folder').disabled = !preferences.native_picker;
    $('output-folder-hint').textContent = preferences.native_picker
      ? 'History always keeps a copy. New takes only; no bulk export.'
      : 'Native folder saving requires Windows. Download WAV is available.';
  },
  onBusy: busy => { for (const node of document.querySelectorAll('[data-output-picker]')) node.disabled = busy; }
});
const draftSaver = new DraftSaveQueue({
  getDraft: () => draft,
  acknowledgeRevision: revision => { draft.revision = revision; },
  persist: snapshot => api('draft', snapshot),
  onState: state => {
    $('save-state').textContent = state.error ? 'Draft not saved — ' + state.error.message
      : state.unsaved ? 'Saving…' : '✓ Saved on this computer';
  }
});

async function api(path, body, raw = false, extraHeaders = {}) {
  let response;
  try {
    response = await fetch('/api/' + path, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': raw ? (body.type || 'application/octet-stream') : 'application/json', ...extraHeaders },
      body: raw ? body : JSON.stringify(body)
    });
  } catch (error) {
    if (path === 'transcribe') throw new Error('The local dictation service could not be reached. Your text is unchanged. Reconnect the workspace and try again.');
    throw error;
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`The local service returned an unreadable response (HTTP ${response.status}). Your existing text is unchanged.`); }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}
function safeAction(action) {
  return (...args) => Promise.resolve().then(() => action(...args)).catch(error => notice(error.message, true));
}
function button(text, action, className = '') {
  const element = document.createElement('button');
  element.textContent = text; element.className = className; element.type = 'button';
  element.addEventListener('click', safeAction(action));
  return element;
}
function element(tag, text, className = '') {
  const el = document.createElement(tag); el.textContent = text; el.className = className; return el;
}
function readEditor() {
  return { ...draft, text: $('script').value, voice: $('voice').value,
    seed: Number($('seed').value), maxTokens: Number($('max-tokens').value), chunkSize: Number($('chunk-size').value) };
}
function changed() {
  draft = readEditor(); draftSaver.markEdited();
  $('save-state').textContent = 'Saving…';
  $('word-count').textContent = `${wordCount(draft.text).toLocaleString()} words · ${draft.text.length.toLocaleString()} characters`;
  $('writing-results').hidden = true;
  clearTimeout(saveTimer); saveTimer = setTimeout(() => saveDraft().catch(error => notice(error.message, true)), 350);
}
function saveDraft() {
  clearTimeout(saveTimer);
  return draftSaver.save();
}
function renderDraft() {
  $('script').value = draft.text || '';
  $('seed').value = draft.seed ?? 1234;
  $('max-tokens').value = draft.maxTokens ?? 1500;
  $('chunk-size').value = draft.chunkSize ?? 150;
  renderVoices(); setMode(draft.mode || 'single', false);
  $('word-count').textContent = `${wordCount(draft.text || '')} words · ${(draft.text || '').length} characters`;
  $('save-state').textContent = '✓ Saved on this computer';
}
async function switchTab(value) {
  stopDictation();
  await saveDraft();
  tab = value;
  for (const page of document.querySelectorAll('.page')) page.hidden = page.id !== value;
  for (const item of document.querySelectorAll('[data-tab]')) {
    item.classList.toggle('active', item.dataset.tab === value);
    item.setAttribute('aria-current', item.dataset.tab === value ? 'page' : 'false');
  }
  $('page-name').textContent = { studio: 'Studio', voices: 'Voice library', history: 'Take history', settings: 'Setup & privacy' }[value];
  if (value === 'voices') await loadVoices();
  if (value === 'history') await loadHistory();
}
function options(select, selected = '') {
  select.replaceChildren();
  const initial = document.createElement('option'); initial.value = ''; initial.textContent = 'Drama’s default voice'; select.append(initial);
  for (const voice of voices) {
    const option = document.createElement('option'); option.value = voice.id; option.textContent = voice.name; select.append(option);
  }
  if (selected && !voices.some(v => v.id === selected)) {
    const missing = document.createElement('option'); missing.value = selected; missing.textContent = 'Voice in Trash — restore it to generate'; select.append(missing);
  }
  select.value = selected;
}
function renderVoices() {
  options($('voice'), draft?.voice || '');
  $('cast').replaceChildren();
  for (let i = 0; i < (draft?.cast || ['', '']).length; i++) {
    const label = element('label', `Speaker ${i} reference`), select = document.createElement('select');
    select.setAttribute('aria-label', `Speaker ${i} reference`);
    options(select, draft.cast[i]);
    select.addEventListener('change', () => { draft.cast[i] = select.value; changed(); });
    label.append(select); $('cast').append(label);
  }
  if ((draft?.cast.length || 0) < 16) $('cast').append(button('＋ Add speaker', () => { draft.cast.push(''); renderVoices(); changed(); }, 'wide secondary'));
  if ((draft?.cast.length || 0) > 2) $('cast').append(button('Remove last speaker', () => { draft.cast.pop(); renderVoices(); changed(); }, 'wide secondary'));
}
function setMode(mode, persist = true) {
  draft.mode = mode;
  $('single-mode').classList.toggle('selected', mode === 'single');
  $('multi-mode').classList.toggle('selected', mode === 'multi');
  $('single-mode').setAttribute('aria-pressed', mode === 'single');
  $('multi-mode').setAttribute('aria-pressed', mode === 'multi');
  $('cast').hidden = $('dialogue-hint').hidden = mode !== 'multi';
  $('voice').disabled = mode === 'multi';
  if (persist) changed();
}
async function loadVoices() {
  voices = await api('voices'); renderVoices(); await renderVoiceList();
}
async function renderVoiceList() {
  const trash = $('voice-trash').checked;
  const data = await api(`voices?q=${encodeURIComponent($('voice-search').value)}&trash=${Number(trash)}`);
  const list = $('voice-list'); list.replaceChildren();
  if (!data.length) list.append(element('div', trash ? 'Your voice trash is empty.' : 'Make it yours. Add your first voice reference.', 'empty'));
  for (const voice of data) {
    const card = element('article', '', 'item'); card.append(element('h3', voice.name), element('p', voice.transcript));
    const actions = element('div', '', 'item-actions');
    if (trash) actions.append(button('Restore voice', async () => { await api(`voices/${voice.id}/restore`, {}); await loadVoices(); }));
    else {
      const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none'; audio.src = `/api/voices/${voice.id}/audio`; card.append(audio);
      actions.append(button('Use in Studio', async () => { draft.voice = voice.id; $('voice').value = voice.id; changed(); await switchTab('studio'); }));
      actions.append(button('Edit', () => { if (dictation?.target === 'voice') stopDictation(); $('voice-id').value = voice.id; $('voice-name').value = voice.name; $('voice-transcript').value = voice.transcript; $('voice-audio').value = ''; voiceFormDirty = false; $('voice-form-title').textContent = 'Edit voice preset'; $('voice-name').focus(); }));
      const download = element('a', 'Download WAV'); download.href = `/api/voices/${voice.id}/audio`; download.download = `${voice.name}.wav`; actions.append(download);
      actions.append(button('Move to Trash', async () => { await api(`voices/${voice.id}/delete`, {}); await loadVoices(); notice('Voice moved to Trash. You can restore it.'); }));
    }
    card.append(actions); list.append(card);
  }
}
async function wavFromFile(file) {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await file.arrayBuffer());
    const samples = decoded.length, channels = decoded.numberOfChannels;
    const data = new ArrayBuffer(44 + samples * 2), view = new DataView(data);
    const ascii = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    ascii(0, 'RIFF'); view.setUint32(4, data.byteLength - 8, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, decoded.sampleRate, true); view.setUint32(28, decoded.sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); ascii(36, 'data'); view.setUint32(40, samples * 2, true);
    const buffers = Array.from({ length: channels }, (_, i) => decoded.getChannelData(i));
    for (let i = 0; i < samples; i++) {
      const sample = Math.max(-1, Math.min(1, buffers.reduce((sum, channel) => sum + channel[i], 0) / channels));
      view.setInt16(44 + i * 2, sample * (sample < 0 ? 32768 : 32767), true);
    }
    return new Uint8Array(data);
  } finally { await context.close(); }
}
function toBase64(bytes) {
  let encoded = '';
  for (let i = 0; i < bytes.length; i += 16384) encoded += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(encoded);
}
async function saveVoice(event) {
  event.preventDefault();
  if (dictation?.target === 'voice') stopDictation();
  const formButton = $('voice-form').querySelector('[type=submit]'); formButton.disabled = true;
  try {
    const file = $('voice-audio').files[0];
    if (!$('voice-id').value && !file) throw new Error('Choose a reference recording first.');
    if (file && file.size > 20 * 1024 * 1024) throw new Error('Choose a recording under 20 MB.');
    const audio = file ? await wavFromFile(file) : null;
    if (audio && audio.byteLength > 20 * 1024 * 1024) throw new Error('Converted WAV exceeds 20 MB. Choose a shorter recording.');
    await api('voices', { id: $('voice-id').value || undefined, name: $('voice-name').value,
      transcript: $('voice-transcript').value, audio: audio ? toBase64(audio) : undefined });
    $('voice-form').reset(); voiceFormDirty = false; $('voice-form-title').textContent = 'Add a voice';
    await loadVoices(); notice('Voice preset saved on this computer.');
  } finally { formButton.disabled = false; }
}
async function generate() {
  if (activeJob) return;
  stopDictation(); await saveDraft();
  const job = await api('generate', readEditor());
  activeJob = job.id; setBusy(true); notice('');
  currentOutputId = null;
  $('output').className = 'output-empty'; $('output').replaceChildren(element('h3', 'Finding the right delivery…'), element('p', 'The model may need time to load. You can keep writing while this take runs.'));
  pollJob();
}
function setBusy(busy) {
  $('generate').disabled = busy; $('cancel').hidden = !busy;
  $('take-state').textContent = busy ? 'Generating on your computer' : 'Ready';
}
async function pollJob() {
  if (!activeJob) return;
  try {
    const job = await api(`history/${activeJob}`);
    $('generation-status').textContent = `${job.status === 'queued' ? 'Preparing model' : 'Generating'} · ${Math.floor(Date.now() / 1000 - job.created)}s`;
    if (['complete', 'failed', 'interrupted', 'cancelled'].includes(job.status)) {
      activeJob = null; setBusy(false); clearTimeout(polling);
      $('generation-status').textContent = job.status === 'complete' ? `Saved locally · ${job.elapsed}s generation` : job.status;
      if (job.status === 'complete') showOutput(job);
      else { $('output').replaceChildren(element('h3', job.status === 'cancelled' ? 'Take cancelled.' : 'This take needs another try.'), element('p', job.error)); notice(job.error || job.status, job.status !== 'cancelled'); }
      if (tab === 'history') await loadHistory();
      return;
    }
  } catch (error) { notice('Connection lost while checking the take. Retrying… ' + error.message, true); }
  polling = setTimeout(pollJob, 1200);
}
function showOutput(job) {
  currentOutputId = job.id;
  $('take-state').textContent = `Saved · ${new Date(job.created * 1000).toLocaleTimeString()}`;
  const container = $('output'); container.className = 'output-playing'; container.replaceChildren();
  container.append(element('h3', 'A new take, ready to hear.'), element('p', job.text.slice(0, 220) + (job.text.length > 220 ? '…' : '')));
  const audio = document.createElement('audio'); audio.controls = true; audio.src = `/api/history/${job.id}/audio`; container.append(audio);
  const link = element('a', '↓ Download WAV'); link.href = audio.src; link.download = `drama-${job.id}.wav`; container.append(link);
  container.append(outputActions(job));
  const settings = element('a', '↓ Save take settings');
  settings.href = 'data:application/json,' + encodeURIComponent(JSON.stringify(job.draft, null, 2)); settings.download = `take-${job.id}.json`; container.append(settings);
}
function outputActions(job) {
  const area = element('div', '', 'take-exports');
  const message = element('p', exportMessage(job), ['error', 'interrupted'].includes(job.export?.status) ? 'export-error' : 'hint');
  message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite'); area.append(message);
  const saveAs = button('Save as…', async () => {
    stopDictation(true);
    const result = await outputControls.saveAs(job.id);
    if (!result.cancelled) notice(`WAV saved: ${result.folder} / ${result.filename}`);
  }, 'secondary');
  saveAs.dataset.outputPicker = ''; saveAs.disabled = outputControls.busy || !outputControls.preferences.native_picker;
  area.append(saveAs);
  if (outputControls.preferences.folder && !['pending', 'saving', 'saved'].includes(job.export?.status)) {
    const retry = button(['error', 'interrupted'].includes(job.export?.status) ? 'Retry folder save' : 'Save to output folder', async () => {
      retry.disabled = true;
      try {
        const result = await outputControls.retry(job.id);
        notice(result.status === 'saved' ? `WAV saved: ${result.filename}` : result.error || 'Automatic folder saving is off.', result.status === 'error');
        const updated = await api(`history/${job.id}`);
        area.replaceWith(outputActions(updated));
      } finally { retry.disabled = false; }
    }, 'secondary');
    area.append(retry);
  }
  if (['pending', 'saving'].includes(job.export?.status)) watchExport(job.id);
  return area;
}
function watchExport(identity) {
  if (exportWatches.has(identity)) return;
  exportWatches.add(identity);
  async function check() {
    try {
      const job = await api(`history/${identity}`);
      if (['pending', 'saving'].includes(job.export?.status)) { setTimeout(check, 1000); return; }
      exportWatches.delete(identity);
      if (currentOutputId === identity) {
        const old = $('output').querySelector('.take-exports');
        if (old) old.replaceWith(outputActions(job));
      }
      if (tab === 'history') await loadHistory();
    } catch { exportWatches.delete(identity); }
  }
  setTimeout(check, 500);
}
async function loadHistory() {
  const trash = $('history-trash').checked;
  history = await api(`history?q=${encodeURIComponent($('history-search').value)}&trash=${Number(trash)}`);
  const list = $('history-list'); list.replaceChildren();
  if (!history.length) list.append(element('div', trash ? 'Your take trash is empty.' : 'Your first take is waiting to happen. Generate a script to start your history.', 'empty'));
  for (const job of history) {
    const card = element('article', '', 'item');
    card.append(element('h3', `${new Date(job.created * 1000).toLocaleString()} · ${job.status}`), element('small', `Seed ${job.seed} · ${job.elapsed}s · ${job.draft?.mode === 'multi' ? 'Dialogue' : 'Single voice'}`), element('p', job.text));
    if (job.error) card.append(element('p', job.error));
    const actions = element('div', '', 'item-actions');
    if (trash) actions.append(button('Restore take', async () => { await api(`history/${job.id}/restore`, {}); await loadHistory(); }));
    else {
      if (job.status === 'complete') {
        const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none'; audio.src = `/api/history/${job.id}/audio`; card.append(audio);
        const link = element('a', 'Download WAV'); link.href = audio.src; link.download = `drama-${job.id}.wav`; actions.append(link);
        card.append(outputActions(job));
      }
      actions.append(button('Restore script & settings', async () => {
        await saveDraft(); draft = { ...job.draft, revision: draft.revision }; renderDraft(); draftSaver.markEdited();
        await saveDraft(); await switchTab('studio'); if (job.status === 'complete') showOutput(job); notice('Script and settings restored.');
      }));
      if (!['running', 'queued'].includes(job.status)) actions.append(button('Move to Trash', async () => { await api(`history/${job.id}/delete`, {}); await loadHistory(); }));
    }
    card.append(actions); list.append(card);
  }
}
async function checkWriting() {
  const snapshot = $('script').value;
  $('check').disabled = true; $('check').textContent = 'Checking locally…';
  const area = $('writing-results'); area.hidden = false; area.replaceChildren(element('p', 'Loading the bundled offline English checker…'));
  try {
    const masked = maskSpeechTags(snapshot), findings = await linter.lint(masked, { language: 'plaintext' });
    if ($('script').value !== snapshot) return;
    area.replaceChildren(element('strong', findings.length ? `${findings.length} writing suggestion${findings.length === 1 ? '' : 's'}` : 'Looking good. No issues found.'));
    area.append(element('p', 'English spelling and grammar · Harper · runs entirely in this browser'));
    for (const finding of findings.slice(0, 40)) {
      const row = element('div', '', 'suggestion'); row.append(element('span', `${finding.get_problem_text()}: ${finding.message()}`));
      const suggestions = finding.suggestions();
      if (suggestions.length) row.append(button('Apply suggestion', async () => {
        if ($('script').value !== snapshot) throw new Error('The script changed. Check writing again for fresh suggestions.');
        undoText = snapshot; $('undo').disabled = false;
        const span = finding.span();
        // Harper indices count Unicode scalar values, not UTF-16 units.
        const chars = Array.from(snapshot), maskedChars = Array.from(masked);
        const replacement = Array.from(await linter.applySuggestion(masked, finding, suggestions[0]));
        const removed = span.end - span.start;
        const inserted = replacement.slice(span.start, replacement.length - (maskedChars.length - span.end));
        chars.splice(span.start, removed, ...inserted);
        $('script').value = chars.join(''); changed();
      }));
      area.append(row);
    }
  } finally { $('check').disabled = false; $('check').textContent = '✓ Check writing'; }
}
function stopDictation(flushFinal = false) { dictation?.stop(flushFinal); }
async function startDictation(target = 'script') {
  const fields = { script: ['script', 'dictate', 'dictation-status'], voice: ['voice-transcript', 'voice-dictate', 'voice-dictation-status'] };
  const report = message => { $(fields[target][2]).textContent = message; notice(message, true); };
  if (!status?.stt) { report('Dictation model is not ready. See Setup & privacy for local setup. Your text is unchanged.'); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { report('Microphone recording needs a current browser on localhost. Your text is unchanged.'); return; }
  if (!dictation) dictation = new DictationController({
    mediaDevices: navigator.mediaDevices, Recorder: MediaRecorder,
    transcribe: audio => api('transcribe', audio, true),
    onText: (destination, text) => {
      const field = $(fields[destination][0]);
      field.value += (field.value.trim() ? ' ' : '') + text;
      if (destination === 'script') changed(); else voiceFormDirty = true;
    },
    onStatus: (destination, message, active) => {
      $(fields[destination][2]).textContent = message;
      const control = $(fields[destination][1]);
      control.textContent = active ? 'Stop dictation' : destination === 'voice' ? 'Dictate reference text' : 'Dictate';
      control.classList.toggle('recording', active);
    },
    onError: (destination, message) => { $(fields[destination][2]).textContent = message; notice(message, true); }
  });
  try { await dictation.toggle(target); } catch (error) { report(dictationErrorMessage(error)); }
}
async function init() {
  draft = await api('draft'); voices = await api('voices'); renderDraft();
  status = await api('status');
  await outputControls.load();
  $('engine-state').textContent = status.engine.status === 'ok' ? 'Local engine connected' : 'Local engine offline';
  $('engine-dot').classList.toggle('offline', status.engine.status !== 'ok');
  $('model-status').textContent = `${status.engine.status === 'ok' ? 'Connected' : 'Offline'} · Drama 3 · CUDA · ${status.engine_url}`;
  $('native-link').href = status.engine_url;
  $('stt-status').textContent = status.stt ? 'Ready · Whisper tiny.en · CPU int8 · English' : 'Not installed. Run setup.py --with-stt (78 MB model, plus Python dependencies). Then restart this workspace.';
  const unfinished = (await api('history')).find(job => ['running', 'queued'].includes(job.status));
  if (unfinished) { activeJob = unfinished.id; setBusy(true); pollJob(); }
}
async function storagePanel() {
  const grid = $('settings').querySelector('.settings-grid');
  const card = element('div', '', 'card form-card');
  card.append(element('h2', 'Storage & migration'));
  const usage = element('p', 'Checking local storage…'); card.append(usage);
  async function refresh() {
    const info = await api('storage');
    usage.textContent = `Database: ${(info.database_bytes / 1048576).toFixed(1)} MB · ${(info.free_bytes / 1073741824).toFixed(1)} GB disk free · ${info.items.filter(i => i.trash).reduce((n, i) => n + i.count, 0)} items in Trash. Backups are retained separately.`;
  }
  card.append(button('Refresh storage usage', refresh, 'secondary'));
  card.append(element('p', 'To reclaim space, empty Trash. A full private database backup is created first. Backups still occupy disk space; remove old backups manually only when you no longer need them.'));
  const confirm = document.createElement('input'); confirm.placeholder = 'Type EMPTY TRASH'; confirm.setAttribute('aria-label', 'Confirm empty Trash'); card.append(confirm);
  card.append(button('Empty Trash & compact database', async () => {
    const result = await api('empty-trash', { confirm: confirm.value }); confirm.value = '';
    await refresh(); notice(`Trash cleared. Recovery backup saved locally: ${result.backup}`);
  }, 'wide danger'));
  card.append(element('h3', 'Import voice export'));
  const exportLink = element('a', 'Download private voice library JSON'); exportLink.href = '/api/voices/export';
  exportLink.download = 'private-voice-library.json'; card.append(exportLink);
  card.append(element('p', 'Import a compatible JSON export with bundled WAV references. Existing presets are never overwritten. Importing creates a backup first. For the original audio.cpp UI, download its WAV references and add them in Voice library with their transcripts.'));
  const file = document.createElement('input'); file.type = 'file'; file.accept = '.json,application/json'; file.setAttribute('aria-label', 'Voice export JSON'); card.append(file);
  card.append(button('Import selected voice export', async () => {
    const source = file.files[0]; if (!source) throw new Error('Choose a voice export JSON first.');
    if (source.size > 30 * 1048576) throw new Error('Import must be under 30 MB. Split larger libraries into batches.');
    const result = await api('voices/import', JSON.parse(await source.text()));
    await loadVoices(); await refresh(); notice(`Imported ${result.imported} voice presets. Originals were preserved.`);
  }, 'wide secondary'));
  grid.append(card); await refresh();
}
for (const nav of document.querySelectorAll('[data-tab]')) nav.addEventListener('click', safeAction(() => switchTab(nav.dataset.tab)));
for (const id of ['script', 'voice', 'seed', 'max-tokens', 'chunk-size']) $(id).addEventListener('input', changed);
$('single-mode').addEventListener('click', () => setMode('single'));
$('multi-mode').addEventListener('click', () => setMode('multi'));
$('format').addEventListener('click', () => { undoText = $('script').value; $('script').value = formatScript(undoText); $('undo').disabled = false; changed(); });
$('undo').addEventListener('click', () => { if (undoText !== null) { const current = $('script').value; $('script').value = undoText; undoText = current; changed(); } });
$('check').addEventListener('click', safeAction(checkWriting));
$('generate').addEventListener('click', safeAction(generate));
$('choose-output-folder').addEventListener('click', safeAction(async () => {
  stopDictation(true);
  $('output-folder-hint').textContent = 'Choose a folder in the Windows dialog. Cancel keeps your current choice.';
  try { await outputControls.choose(); }
  finally {
    const preferences = await outputControls.load();
    notice(preferences.folder ? 'New completed takes will save to your selected folder. Existing history was not exported.' : 'Folder choice unchanged. History keeps every take.');
  }
}));
$('clear-output-folder').addEventListener('click', safeAction(async () => {
  await outputControls.clear(); notice('Automatic folder saving turned off. Existing WAV files and history are untouched.');
}));
$('cancel').addEventListener('click', safeAction(async () => {
  if (!activeJob) return;
  const result = await api(`history/${activeJob}/cancel`, {});
  if (result.status === 'cancelling') $('generation-status').textContent = 'Cancelling… The engine may still be winding down.';
  else await pollJob(); // Completion already committed; show its terminal state.
}));
$('dictate').addEventListener('click', safeAction(() => startDictation('script')));
$('voice-dictate').addEventListener('click', safeAction(() => startDictation('voice')));
for (const id of ['voice-name', 'voice-transcript', 'voice-audio']) $(id).addEventListener('input', () => { voiceFormDirty = true; });
$('voice-form').addEventListener('submit', event => { event.preventDefault(); safeAction(saveVoice)(event); });
$('voice-new').addEventListener('click', () => { if (dictation?.target === 'voice') stopDictation(); $('voice-form').reset(); voiceFormDirty = false; $('voice-form-title').textContent = 'Add a voice'; });
$('add-voice-shortcut').addEventListener('click', safeAction(async () => { await switchTab('voices'); $('voice-name').focus(); }));
for (const id of ['voice-search', 'voice-trash']) $(id).addEventListener('input', safeAction(renderVoiceList));
for (const id of ['history-search', 'history-trash']) $(id).addEventListener('input', safeAction(loadHistory));
$('backup').addEventListener('click', safeAction(async () => { const backup = await api('backup', {}); $('backup-status').textContent = `Saved in the private data/backups folder: ${backup.file}`; }));
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); safeAction(generate)(); }
  if (event.altKey && ['1', '2', '3', '4'].includes(event.key)) { event.preventDefault(); safeAction(() => switchTab(['studio', 'voices', 'history', 'settings'][Number(event.key) - 1]))(); }
  if (event.key === 'Escape' && dictation?.stream) stopDictation(true);
});
document.addEventListener('visibilitychange', () => { if (document.hidden) { stopDictation(); if (draftSaver.unsaved) saveDraft().catch(() => {}); } });
window.addEventListener('pagehide', () => {
  stopDictation();
  if (draftSaver.unsaved && draft) navigator.sendBeacon('/api/draft', new Blob([JSON.stringify(draft)], { type: 'application/json' }));
});
window.addEventListener('beforeunload', event => { if (draftSaver.unsaved || voiceFormDirty) { event.preventDefault(); event.returnValue = ''; } });
init().then(storagePanel).catch(error => notice('Workspace could not load: ' + error.message, true));
