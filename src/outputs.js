export function exportMessage(job) {
  const result = job.export || {};
  if (result.status === 'saved') return `WAV saved to ${result.folder} / ${result.filename}`;
  if (['pending', 'saving'].includes(result.status)) return 'Saved in history. Saving a WAV to your output folder…';
  if (['error', 'interrupted'].includes(result.status)) return result.error || 'External save needs another try. Audio is safe in history.';
  return 'Saved in history. Choose an output folder to automatically save future takes.';
}

export class OutputControls {
  constructor({ api, onPreferences, onBusy = () => {} }) {
    this.api = api; this.onPreferences = onPreferences; this.onBusy = onBusy;
    this.preferences = {}; this.busy = false;
  }
  async load() {
    this.preferences = await this.api('output-folder');
    this.onPreferences(this.preferences); return this.preferences;
  }
  async action(path) {
    return this.api(path, {}, false, { 'X-Output-Token': this.preferences.action_token });
  }
  async native(path) {
    if (this.busy) throw new Error('Finish or cancel the open file picker first.');
    this.busy = true; this.onBusy(true);
    try { return await this.action(path); }
    finally { this.busy = false; this.onBusy(false); }
  }
  async choose() {
    const result = await this.native('output-folder/choose');
    if (!result.cancelled) { this.preferences = result; this.onPreferences(result); }
    return result;
  }
  async clear() {
    this.preferences = await this.action('output-folder/clear');
    this.onPreferences(this.preferences);
  }
  saveAs(id) { return this.native(`history/${encodeURIComponent(id)}/save-as`); }
  retry(id) { return this.action(`history/${encodeURIComponent(id)}/export`); }
}
