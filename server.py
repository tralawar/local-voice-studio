"""Local-only Drama Studio. Python 3.10+, no runtime dependencies unless using STT."""
import argparse
import base64
import io
import json
import os
import shutil
import sys
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager, closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from outputs import Outputs

ROOT = Path(__file__).resolve().parent
MAX_BODY = 32 * 1024 * 1024


@contextmanager
def exclusive_data_lock(root):
    """Prevent a second workspace process from resetting live generation state."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / '.instance.lock').open('a+b')
    try:
        lock.seek(0, 2)
        if lock.tell() == 0: lock.write(b'0'); lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError('This data directory is already in use. Reuse its existing workspace or choose another --data directory.')
    try:
        yield
    finally:
        lock.seek(0)
        if os.name == 'nt':
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def validate_draft(body):
    if not isinstance(body, dict): raise ValueError('Draft must be a JSON object.')
    text, mode = body.get('text', ''), body.get('mode', 'single')
    cast = body.get('cast', ['', ''])
    if not isinstance(text, str) or len(text) > 30000 or mode not in ('single', 'multi'):
        raise ValueError('Invalid script or generation mode.')
    if not isinstance(cast, list) or not 2 <= len(cast) <= 16 or not all(isinstance(v, str) and len(v) <= 100 for v in cast):
        raise ValueError('Cast must contain 2–16 voice IDs.')
    voice = body.get('voice', '')
    if not isinstance(voice, str) or len(voice) > 100: raise ValueError('Invalid voice ID.')
    seed, tokens, chunk = int(body.get('seed', 1234)), int(body.get('maxTokens', 1500)), int(body.get('chunkSize', 150))
    if not 0 <= seed <= 2147483647 or not 1 <= tokens <= 8000 or not 20 <= chunk <= 500:
        raise ValueError('Seed, token budget or chunk size is outside the supported range.')
    return {'text': text, 'mode': mode, 'cast': cast, 'voice': voice, 'seed': seed,
            'maxTokens': tokens, 'chunkSize': chunk, 'revision': int(body.get('revision', 0))}


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'studio.sqlite3'
        with self.connect() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                  kind TEXT, id TEXT, body TEXT NOT NULL, audio BLOB,
                  updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            ''')
            c.execute("INSERT OR IGNORE INTO metadata VALUES ('schema','1')")
        for job in self.list('jobs'):
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', error='Studio stopped before this take finished. Restore its text and try again.')
                self.put('jobs', job['id'], job)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=20)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put(self, kind, identity, body, audio=None, revision=None):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT body,audio FROM documents WHERE kind=? AND id=?', (kind, identity)).fetchone()
            if revision is not None and old and json.loads(old[0]).get('revision', 0) != revision:
                raise ValueError('Draft changed in another tab. Reload before overwriting it.')
            c.execute('INSERT INTO documents VALUES (?,?,?,?,?,0) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,audio=excluded.audio,updated=excluded.updated,deleted=0',
                      (kind, identity, json.dumps(body), audio if audio is not None else (old[1] if old else None), time.time()))
        return body

    def get(self, kind, identity, audio=False):
        with self.connect() as c:
            row = c.execute('SELECT body,audio FROM documents WHERE kind=? AND id=? AND deleted=0', (kind, identity)).fetchone()
        if not row:
            raise KeyError('Item not found')
        return row[1] if audio else json.loads(row[0])

    def list(self, kind, query='', trash=False):
        with self.connect() as c:
            rows = c.execute('SELECT body FROM documents WHERE kind=? AND deleted=? ORDER BY updated DESC', (kind, int(trash))).fetchall()
        return [b for row in rows if (b := json.loads(row[0])) and query.lower() in json.dumps(b).lower()]

    def delete(self, kind, identity, restore=False):
        with self.connect() as c:
            c.execute('UPDATE documents SET deleted=? WHERE kind=? AND id=?', (int(not restore), kind, identity))

    def backup(self):
        folder = self.root / 'backups'
        folder.mkdir(exist_ok=True)
        target = folder / f'studio-{time.time_ns()}.sqlite3'
        with self.connect() as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
        return target.name

    def usage(self):
        with self.connect() as c:
            rows = c.execute('SELECT kind,deleted,COUNT(*),COALESCE(SUM(LENGTH(audio)),0) FROM documents GROUP BY kind,deleted').fetchall()
        return {'database_bytes': self.db.stat().st_size,
                'free_bytes': shutil.disk_usage(self.root).free,
                'items': [{'kind': r[0], 'trash': bool(r[1]), 'count': r[2], 'audio_bytes': r[3]} for r in rows]}

    def empty_trash(self):
        backup = self.backup()
        with self.connect() as c:
            c.execute('DELETE FROM documents WHERE deleted=1')
        with self.connect() as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            c.execute('VACUUM')
        return backup

    def import_voices(self, data):
        entries = data.get('voices')
        if data.get('schema') != 'local-voice-studio.voices.v1' or not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise ValueError('Choose a local-voice-studio.voices.v1 export containing 1–100 voices.')
        validated = []
        for entry in entries:
            name, transcript = str(entry.get('name', '')).strip(), str(entry.get('transcript', '')).strip()
            audio = base64.b64decode(entry.get('audio', ''), validate=True)
            if not name or len(name) > 120 or not transcript or len(transcript) > 10000 or not audio.startswith(b'RIFF') or len(audio) > 20 * 1024 * 1024:
                raise ValueError('Import contains an invalid voice, transcript, or WAV recording.')
            identity = str(uuid.uuid4())
            validated.append((identity, {'id': identity, 'name': name, 'transcript': transcript, 'created': time.time()}, audio))
        backup = self.backup()
        with self.connect() as c:
            for identity, body, audio in validated:
                c.execute('INSERT INTO documents VALUES (?,?,?,?,?,0)', ('voices', identity, json.dumps(body), audio, time.time()))
        return {'imported': len(validated), 'backup': backup}


class Studio:
    def __init__(self, data, engine, stt=None):
        parts = urlsplit(engine)
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('Engine must be a loopback HTTP address')
        self.engine = engine.rstrip('/')
        self.engine_host, self.engine_port = parts.hostname, parts.port or 80
        self.store = Store(data)
        self.outputs = Outputs(self.store)
        self.stt_path = Path(stt).resolve() if stt else None
        self.whisper = None
        self.stt_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.jobs_lock = threading.Lock()
        self.connections = {}
        self.cancelled = set()

    def engine_request(self, path, data=None, mime='application/json', job=None):
        connection = HTTPConnection(self.engine_host, self.engine_port, timeout=900)
        if job:
            with self.jobs_lock:
                if job in self.cancelled:
                    raise RuntimeError('Cancelled')
                self.connections[job] = connection
        try:
            connection.request('POST' if data is not None else 'GET', path, data, {'Content-Type': mime})
            response = connection.getresponse()
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise RuntimeError('Engine response exceeds the 32 MB per-take limit. Use a shorter script.')
            if response.status >= 400:
                raise RuntimeError(f'Engine returned {response.status}: {body[:800].decode(errors="replace")}')
            return body
        finally:
            connection.close()
            if job:
                with self.jobs_lock:
                    self.connections.pop(job, None)

    def status(self):
        try:
            health = json.loads(self.engine_request('/health'))
        except Exception as error:
            health = {'status': 'offline', 'error': str(error)}
        import importlib.util
        stt_files = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')
        stt_ready = bool(self.stt_path and all((self.stt_path / f).is_file() for f in stt_files)
                         and importlib.util.find_spec('faster_whisper'))
        return {'engine': health, 'engine_url': self.engine, 'stt': stt_ready,
                'stt_model': 'Whisper tiny.en · CPU int8', 'storage': 'Local SQLite · schema 1'}

    def generate(self, draft):
        draft = validate_draft(draft)
        if not self.generation_lock.acquire(blocking=False):
            raise ValueError('A take is already generating. Wait for it to finish or cancel it.')
        try:
            text = str(draft.get('text', '')).strip()
            if not text or len(text) > 30000:
                raise ValueError('Enter between 1 and 30,000 characters.')
            seed = int(draft.get('seed', 1234))
            max_tokens = int(draft.get('maxTokens', 1500))
            if not 1 <= max_tokens <= 8000:
                raise ValueError('Token budget must be between 1 and 8,000.')
            voices = draft.get('cast', []) if draft.get('mode') == 'multi' else ([draft['voice']] if draft.get('voice') else [])
            if len(voices) > 16:
                raise ValueError('At most 16 speakers are supported.')
            # Validate every reference before accepting a job.
            for identity in voices:
                if identity:
                    voice = self.store.get('voices', identity)
                    if not voice.get('transcript', '').strip():
                        raise ValueError('Every voice requires its exact reference transcript.')
            identity = str(uuid.uuid4())
            job = {'id': identity, 'status': 'queued', 'text': text, 'draft': draft, 'seed': seed,
                   'created': time.time(), 'elapsed': 0, 'error': ''}
            self.store.put('jobs', identity, job)
            threading.Thread(target=self.run_generation, args=(job, voices, max_tokens), daemon=True).start()
            return job
        except Exception:
            self.generation_lock.release()
            raise

    def run_generation(self, job, voices, max_tokens):
        start = time.monotonic()
        completed = False
        try:
            job['status'] = 'running'
            self.store.put('jobs', job['id'], job)
            options = {'text_chunk_size': int(job['draft'].get('chunkSize', 150))}
            body = {'model': 'drama-3', 'input': job['text'], 'seed': job['seed'],
                    'response_format': 'wav', 'max_tokens': max_tokens, 'options': options}
            references = []
            for index, identity in enumerate(voices):
                if not identity:
                    continue
                if self.is_cancelled(job['id']):
                    raise RuntimeError('Cancelled')
                voice = self.store.get('voices', identity)
                audio = self.store.get('voices', identity, audio=True)
                result = json.loads(self.engine_request('/v1/ui/upload', audio, 'audio/wav', job=job['id']))
                if job['draft'].get('mode') == 'multi':
                    references.append({'text': f'<|speaker:{index}|> ' + voice['transcript'], 'audio_path': result['path']})
                else:
                    body.update(voice_ref=result['path'], reference_text=voice['transcript'])
            if references:
                options['multi_reference_cond'] = json.dumps(references)
            audio = self.engine_request('/v1/audio/speech', json.dumps(body).encode(), job=job['id'])
            if not audio.startswith(b'RIFF'):
                raise RuntimeError('Engine did not return WAV audio.')
            # Cancellation acceptance and completion persistence share one lock.
            # Once completion owns it, cancel waits and returns the terminal job.
            with self.jobs_lock:
                if job['id'] in self.cancelled:
                    raise RuntimeError('Cancelled')
                job.update(status='complete', elapsed=round(time.monotonic() - start, 2))
                job['export'] = {'status': 'pending' if self.outputs.folder() else 'off'}
                self.store.put('jobs', job['id'], job, audio)
                completed = True
        except Exception as error:
            with self.jobs_lock:
                cancelled = job['id'] in self.cancelled
                job.update(status='cancelled' if cancelled else 'failed',
                           error='Cancelled by user. Script and settings remain in history.' if cancelled else str(error), elapsed=round(time.monotonic() - start, 2))
                self.store.put('jobs', job['id'], job)
        finally:
            with self.jobs_lock:
                self.cancelled.discard(job['id'])
            self.generation_lock.release()
        if completed and job.get('export', {}).get('status') == 'pending':
            self.outputs.automatic(job['id'])

    def is_cancelled(self, identity):
        with self.jobs_lock:
            return identity in self.cancelled

    def cancel(self, identity):
        with self.jobs_lock:
            job = self.store.get('jobs', identity)
            if job['status'] not in ('running', 'queued'):
                return job
            self.cancelled.add(identity)
            connection = self.connections.get(identity)
        if connection and connection.sock:
            import socket
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if connection:
            connection.close()
        return {'status': 'cancelling'}

    def transcribe(self, audio, mime='application/octet-stream'):
        mime = mime.split(';', 1)[0].strip().lower()
        if mime not in ('application/octet-stream', 'audio/webm', 'video/webm', 'audio/mp4', 'video/mp4', 'audio/ogg', 'audio/wav', 'audio/x-wav'):
            raise ValueError('Unsupported recording format. Use WebM/Opus, MP4/AAC, Ogg or WAV audio.')
        if not audio:
            raise ValueError('No audio was captured. Record for a moment before pressing Stop, then try again.')
        if not self.stt_path or not all((self.stt_path / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')):
            raise ValueError('Dictation model is not installed. Run setup.py --with-stt first (78 MB).')
        if not self.stt_lock.acquire(blocking=False):
            raise ValueError('Transcription is busy. Wait for the current audio segment.')
        started = time.monotonic()
        stage = 'dependencies'
        try:
            try:
                import av
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as error:
                raise RuntimeError('Local transcription dependencies could not load. Run setup.py --with-stt in this workspace, then relaunch it.') from error
            if self.whisper is None:
                stage = 'model'
                try:
                    self.whisper = WhisperModel(str(self.stt_path), device='cpu', compute_type='int8',
                                                cpu_threads=4, local_files_only=True)
                except Exception as error:
                    raise RuntimeError('The local Whisper model could not load. Verify all four model files and the CPU runtime, then relaunch the workspace.') from error
            stage = 'decode/transcription'
            try:
                segments, info = self.whisper.transcribe(io.BytesIO(audio), language='en', beam_size=1,
                    condition_on_previous_text=False, vad_filter=True)
                text = ' '.join(segment.text.strip() for segment in segments)
            except (av.error.InvalidDataError, av.error.EOFError) as error:
                raise ValueError('The recording could not be decoded. Record a complete audio segment and try again; WebM/Opus, MP4/AAC and WAV are supported.') from error
            except av.error.FFmpegError as error:
                raise RuntimeError('The local audio decoder failed. Verify the PyAV installation and try another supported recording format.') from error
            return {'text': text, 'elapsed': round(time.monotonic() - started, 3), 'language': info.language}
        except Exception as error:
            # Technical diagnostics only: never log the recording or transcript.
            print(f'dictation_error stage={stage} type={type(error).__name__} mime={mime} bytes={len(audio)}', file=sys.stderr, flush=True)
            raise
        finally:
            self.stt_lock.release()


def handler_for(studio, static=ROOT / 'dist'):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never put prompts, reference transcripts or audio in access logs.

        def send(self, status, body, mime='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; worker-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            host = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            return host in allowed and self.headers.get('Origin', 'http://' + host) in {'http://' + host}

        def read_body(self):
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= MAX_BODY:
                raise ValueError('Request must be between 1 byte and 32 MB.')
            return self.rfile.read(size)

        def authorize_output(self, body):
            import secrets
            if self.headers.get('Origin') != 'http://' + self.headers.get('Host', '') or not secrets.compare_digest(self.headers.get('X-Output-Token', ''), studio.outputs.token):
                self.send(403, {'error': 'Open this workspace locally and use its output controls to select a destination.'})
                return False
            if body != {}: raise ValueError('Output destinations must be chosen with the native picker. No path arguments are accepted.')
            return True

        def route(self, method):
            if not self.allowed():
                return self.send(403, {'error': 'Only same-origin loopback requests are allowed.'})
            path = '/' + urlsplit(self.path).path.strip('/')
            query = parse_qs(urlsplit(self.path).query)
            try:
                if method == 'GET':
                    if path == '/api/status':
                        return self.send(200, studio.status())
                    if path == '/api/storage':
                        return self.send(200, studio.store.usage())
                    if path == '/api/output-folder':
                        return self.send(200, studio.outputs.preferences())
                    if path == '/api/draft':
                        try:
                            draft = studio.store.get('draft', 'current')
                        except KeyError:
                            draft = {'revision': 0, 'text': '', 'mode': 'single', 'voice': '', 'seed': 1234, 'maxTokens': 1500, 'chunkSize': 150, 'cast': ['', '']}
                        return self.send(200, draft)
                    if path in ('/api/voices', '/api/history'):
                        return self.send(200, studio.store.list('voices' if path.endswith('voices') else 'jobs', query.get('q', [''])[0], query.get('trash') == ['1']))
                    if path == '/api/voices/export':
                        entries = [{**voice, 'audio': base64.b64encode(studio.store.get('voices', voice['id'], True)).decode()}
                                   for voice in studio.store.list('voices')]
                        return self.send(200, {'schema': 'local-voice-studio.voices.v1', 'voices': entries})
                    bits = path.strip('/').split('/')
                    if len(bits) in (3, 4) and bits[:2] in (['api', 'voices'], ['api', 'history']):
                        kind = 'voices' if bits[1] == 'voices' else 'jobs'
                        if len(bits) == 4 and bits[3] == 'audio':
                            audio = studio.store.get(kind, bits[2], audio=True)
                            if not audio:
                                raise KeyError('No audio available for this item')
                            return self.send(200, audio, 'audio/wav')
                        if len(bits) == 3:
                            return self.send(200, studio.store.get(kind, bits[2]))
                    target = (static / ('index.html' if path == '/' else path.lstrip('/'))).resolve()
                    if not target.is_relative_to(static.resolve()) or not target.is_file():
                        return self.send(404, {'error': 'File not found'})
                    import mimetypes
                    return self.send(200, target.read_bytes(), mimetypes.guess_type(target)[0] or 'application/octet-stream')
                if method == 'POST':
                    raw = self.read_body()
                    if path == '/api/transcribe':
                        return self.send(200, studio.transcribe(raw, self.headers.get('Content-Type', 'application/octet-stream')))
                    body = json.loads(raw)
                    if path in ('/api/output-folder/choose', '/api/output-folder/clear'):
                        if not self.authorize_output(body): return
                        if path == '/api/output-folder/choose': return self.send(200, studio.outputs.choose())
                        if path == '/api/output-folder/clear': return self.send(200, studio.outputs.clear())
                    if path == '/api/draft':
                        body = validate_draft(body)
                        revision = int(body.get('revision', 0))
                        body['revision'] = revision + 1
                        return self.send(200, studio.store.put('draft', 'current', body, revision=revision))
                    if path == '/api/voices':
                        name, transcript = str(body.get('name', '')).strip(), str(body.get('transcript', '')).strip()
                        if not name or not transcript or len(name) > 120 or len(transcript) > 10000:
                            raise ValueError('A voice needs a name (1–120 characters) and exact transcript (1–10,000 characters).')
                        identity = body.get('id') or str(uuid.uuid4())
                        audio = base64.b64decode(body['audio'], validate=True) if body.get('audio') else None
                        if audio is not None and (not audio.startswith(b'RIFF') or len(audio) > 20 * 1024 * 1024):
                            raise ValueError('Choose WAV audio under 20 MB.')
                        if audio is None:
                            studio.store.get('voices', identity)
                        return self.send(200, studio.store.put('voices', identity, {'id': identity, 'name': name, 'transcript': transcript, 'created': time.time()}, audio))
                    if path == '/api/voices/import':
                        return self.send(200, studio.store.import_voices(body))
                    if path == '/api/generate':
                        return self.send(202, studio.generate(body))
                    if path == '/api/backup':
                        return self.send(200, {'file': studio.store.backup()})
                    if path == '/api/empty-trash':
                        if body.get('confirm') != 'EMPTY TRASH':
                            raise ValueError('Type EMPTY TRASH to confirm. A local backup is created first.')
                        if studio.generation_lock.locked():
                            raise ValueError('Wait for generation to finish before compacting storage.')
                        return self.send(200, {'backup': studio.store.empty_trash()})
                    bits = path.strip('/').split('/')
                    if len(bits) == 4 and bits[0] == 'api' and bits[1] in ('voices', 'history'):
                        kind = 'voices' if bits[1] == 'voices' else 'jobs'
                        if kind == 'jobs' and bits[3] in ('save-as', 'export'):
                            if not self.authorize_output(body): return
                            return self.send(200, studio.outputs.save_as(bits[2]) if bits[3] == 'save-as' else studio.outputs.export(bits[2]))
                        if bits[3] == 'cancel' and kind == 'jobs':
                            return self.send(200, studio.cancel(bits[2]))
                        if bits[3] in ('delete', 'restore'):
                            item = studio.store.get(kind, bits[2]) if bits[3] == 'delete' else None
                            if item and item.get('status') in ('queued', 'running'):
                                raise ValueError('Cancel this take before deleting it.')
                            studio.store.delete(kind, bits[2], bits[3] == 'restore')
                            return self.send(200, {'ok': True})
                    return self.send(404, {'error': 'Unknown action'})
            except KeyError as error:
                return self.send(404, {'error': str(error)})
            except (ValueError, json.JSONDecodeError) as error:
                return self.send(409 if str(error).startswith('Draft changed') else 400, {'error': str(error)})
            except Exception as error:
                return self.send(503, {'error': str(error)})

        def do_GET(self):
            self.route('GET')

        def do_POST(self):
            self.route('POST')
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8046)
    parser.add_argument('--engine', default=os.environ.get('DRAMA_ENGINE_URL', 'http://127.0.0.1:8080'))
    parser.add_argument('--data', default=os.environ.get('DRAMA_STUDIO_DATA', str(ROOT / 'data')))
    parser.add_argument('--stt-model', default=str(ROOT / 'models' / 'whisper-tiny.en'))
    parser.add_argument('--static', type=Path, default=ROOT / 'dist', help='Operator-selected built UI directory')
    args = parser.parse_args()
    with exclusive_data_lock(args.data):
        app = Studio(args.data, args.engine, args.stt_model)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app, args.static.resolve()))
        print(f'Local Voice Studio ready at http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
