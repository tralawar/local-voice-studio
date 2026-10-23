"""Exports only to native-picker-authorized destinations; history remains the primary copy."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent


def take_filename(job):
    identity = re.sub(r'[^A-Za-z0-9_-]', '', str(job['id']))[:32] or 'take'
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime(job['created']))
    return f'take-{stamp}-{identity}.wav'


def approved_folder(path):
    if not Path(path).is_absolute(): raise ValueError('The native picker must return an absolute folder selection.')
    selected = Path(path).resolve(strict=True)
    if not selected.is_dir(): raise ValueError('Choose an existing folder.')
    stat = selected.stat()
    return {'path': str(selected), 'device': stat.st_dev, 'inode': stat.st_ino, 'id': str(uuid.uuid4())}


def check_folder(folder):
    path = Path(folder['path'])
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError('The selected folder moved or changed. Choose the folder again.')
    stat = path.stat()
    if (stat.st_dev, stat.st_ino) != (folder['device'], folder['inode']):
        raise ValueError('The selected folder was replaced. Choose the folder again to authorize it.')
    return path


def validate_filename(name):
    if not name or len(name) > 180 or name != name.strip(' .') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ValueError('Choose a WAV filename without reserved characters or trailing spaces/dots.')
    if name.split('.')[0].rstrip(' .').upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Choose a different filename; that name is reserved by Windows.')
    if Path(name).suffix.lower() != '.wav': raise ValueError('Choose a filename ending in .wav.')


def atomic_write(folder, name, audio):
    """Stage and publish by verified Windows directory/file handles, never paths."""
    directory = check_folder(folder); validate_filename(name)
    if os.name != 'nt': raise ValueError('Managed output saving currently requires Windows. Use Download WAV on other platforms.')
    from windows_outputs import write
    write(folder, name, audio)
    check_folder(folder)
    return directory / name


class Outputs:
    def __init__(self, store, picker=None):
        self.store = store
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.picker_lock = threading.Lock()
        self.picker = picker or self.native_picker
        # Never export old takes automatically on restart, including interrupted writes.
        for job in store.list('jobs'):
            if job.get('export', {}).get('status') in ('pending', 'saving'):
                job['export'].update(status='interrupted', error='External saving was interrupted. Audio is safe in history. Retry saving when ready.')
                store.put('jobs', job['id'], job)

    def folder(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='output_folder'").fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def preferences(self):
        folder = self.folder()
        return {'folder': folder['path'] if folder else None, 'native_picker': sys.platform == 'win32',
                'action_token': self.token}

    def native_picker(self, kind, initial='', name='take.wav'):
        if sys.platform != 'win32': raise ValueError('Native output selection currently requires Windows. Download WAV remains available.')
        command = [sys.executable, str(ROOT / 'output_picker.py'), kind, '--initial', initial, '--name', name]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            raise ValueError('The file picker timed out and closed. Choose the folder or Save as again.') from error
        try: selection = json.loads(result.stdout)
        except (ValueError, TypeError): raise ValueError('The native file picker could not open. Check Python/Tkinter and your Windows desktop.')
        if result.returncode or selection.get('error'): raise ValueError(selection.get('error', 'The native picker failed.'))
        return selection.get('path')

    def choose(self):
        if not self.picker_lock.acquire(blocking=False): raise ValueError('A native picker is already open. Finish or cancel it first.')
        try:
            old = self.folder()
            selected = self.picker('folder', old['path'] if old else '')
            if not selected: return {**self.preferences(), 'cancelled': True}
            folder = approved_folder(selected)
            with self.lock, self.store.connect() as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('output_folder',?)", (json.dumps(folder),))
            return self.preferences()
        finally: self.picker_lock.release()

    def clear(self):
        with self.lock, self.store.connect() as db: db.execute("DELETE FROM metadata WHERE key='output_folder'")
        return self.preferences()

    def _save_result(self, identity, result, key='export'):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM documents WHERE kind='jobs' AND id=? AND deleted=0", (identity,)).fetchone()
            if not row: raise KeyError('Take no longer available')
            job = json.loads(row[0]); job[key] = result
            db.execute("UPDATE documents SET body=?,updated=? WHERE kind='jobs' AND id=? AND deleted=0", (json.dumps(job), time.time(), identity))
        return result

    def export(self, identity):
        with self.lock:
            job = self.store.get('jobs', identity)
            if job['status'] != 'complete': raise ValueError('Only a completed take can be saved. Its history remains unchanged.')
            folder = self.folder()
            if not folder: return self._save_result(identity, {'status': 'off'})
            audio = self.store.get('jobs', identity, True)
            digest = hashlib.sha256(audio).hexdigest()
            previous = job.get('export', {})
            result = {'status': 'saving', 'folder': folder['path'], 'folder_id': folder['id'], 'sha256': digest}
            try:
                directory = check_folder(folder)
                # Recover a previously published file after interruption; never silently overwrite it.
                name = previous.get('filename') if previous.get('folder_id') == folder['id'] else None
                if name:
                    validate_filename(name)
                    from windows_outputs import matches
                    if matches(folder, name, audio):
                        return self._save_result(identity, {**result, 'status': 'saved', 'filename': name})
                base = Path(take_filename(job))
                for collision in range(10000):
                    name = base.name if collision == 0 else f'{base.stem} ({collision + 1}).wav'
                    result['filename'] = name
                    self._save_result(identity, result)
                    try: atomic_write(folder, name, audio)
                    except FileExistsError: continue
                    return self._save_result(identity, {**result, 'status': 'saved'})
                raise ValueError('Too many conflicting filenames. Choose another folder or use Save as.')
            except Exception as error:
                return self._save_result(identity, {**result, 'status': 'error', 'error': f'Could not save the external WAV: {error}. Audio is safe in history. Reconnect the disk or choose another folder, then retry.'})

    def automatic(self, identity):
        try: return self.export(identity)
        except Exception:
            # A database/disk failure here must never relabel the durable completed generation.
            print('External export status could not be updated; completed audio remains in history.', file=sys.stderr, flush=True)

    def save_as(self, identity):
        job = self.store.get('jobs', identity)
        if job['status'] != 'complete': raise ValueError('Only completed takes can be saved.')
        if not self.picker_lock.acquire(blocking=False): raise ValueError('A native picker is already open. Finish or cancel it first.')
        try:
            folder = self.folder()
            selected = self.picker('file', folder['path'] if folder else '', take_filename(job))
            if not selected: return {'cancelled': True}
            selected = Path(selected)
            if not selected.is_absolute(): raise ValueError('The native picker must return an absolute local selection. Choose the file again.')
            validate_filename(selected.name)
            folder = approved_folder(selected.parent)
            try: target = atomic_write(folder, selected.name, self.store.get('jobs', identity, True))
            except FileExistsError as error: raise ValueError('That filename already exists. Nothing was overwritten. Choose another name with Save as.') from error
            return self._save_result(identity, {'status': 'saved', 'folder': str(target.parent), 'filename': target.name}, 'save_as')
        finally: self.picker_lock.release()
