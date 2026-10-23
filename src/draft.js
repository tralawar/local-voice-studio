// An edit stays unsaved until the matching request has been acknowledged.
// Requests are serialized so newer snapshots use the latest server revision.
export class DraftSaveQueue {
  constructor({ getDraft, acknowledgeRevision, persist, onState = () => {} }) {
    Object.assign(this, { getDraft, acknowledgeRevision, persist, onState });
    this.version = 0;
    this.acknowledged = 0;
    this.pending = false;
    this.error = null;
    this.queue = Promise.resolve();
  }
  get unsaved() { return this.pending || this.version !== this.acknowledged; }
  markEdited() { this.version++; this.onState(this); }
  save() {
    this.queue = this.queue.catch(() => {}).then(async () => {
      if (!this.unsaved) return;
      const version = this.version;
      const snapshot = structuredClone(this.getDraft());
      this.pending = true;
      this.error = null;
      this.onState(this);
      try {
        const result = await this.persist(snapshot);
        this.acknowledgeRevision(result.revision);
        this.acknowledged = version;
      } catch (error) {
        this.error = error;
        throw error;
      } finally {
        this.pending = false;
        this.onState(this);
      }
    });
    return this.queue;
  }
}
