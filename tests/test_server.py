import base64
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import wave
from contextlib import closing
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Store, Studio, handler_for, exclusive_data_lock


def fixture():
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\0\0' * 16000)
    return out.getvalue()


class PersistenceTests(unittest.TestCase):
    def test_cancel_waits_for_completion_commit_and_does_not_claim_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = Studio(directory, 'http://127.0.0.1:1')
            studio.engine_request = lambda *args, **kwargs: fixture()
            reached, release, returned = threading.Event(), threading.Event(), threading.Event()
            original = studio.store.put
            result = []
            def intercepted(kind, identity, body, *args, **kwargs):
                if kind == 'jobs' and body.get('status') == 'complete':
                    reached.set()
                    if not release.wait(5): raise RuntimeError('Test commit gate timed out')
                return original(kind, identity, body, *args, **kwargs)
            studio.store.put = intercepted
            job = studio.generate({'text': 'Synthetic completion boundary'})
            self.assertTrue(reached.wait(5))
            def cancel():
                result.append(studio.cancel(job['id'])); returned.set()
            thread = threading.Thread(target=cancel)
            thread.start()
            try:
                self.assertFalse(returned.wait(.1), 'Cancel returned acceptance before completion commit resolved')
            finally:
                release.set(); thread.join(5)
            self.assertTrue(returned.is_set())
            self.assertEqual(result[0]['status'], 'complete')
            self.assertEqual(studio.store.get('jobs', job['id'])['status'], 'complete')
            self.assertEqual(studio.store.get('jobs', job['id'], True), fixture())

    def test_data_directory_rejects_a_second_active_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            with exclusive_data_lock(directory):
                with self.assertRaises(RuntimeError):
                    with exclusive_data_lock(directory): pass
            with exclusive_data_lock(directory): pass

    def test_import_is_validated_atomic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.put('voices', 'original', {'id': 'original', 'name': 'Original', 'transcript': 'Test'}, fixture())
            good = {'name': 'Imported', 'id': 'original', 'transcript': 'Synthetic', 'audio': base64.b64encode(fixture()).decode()}
            with self.assertRaises(ValueError):
                store.import_voices({'schema': 'local-voice-studio.voices.v1', 'voices': [good, {'name': 'bad'}]})
            self.assertEqual(len(store.list('voices')), 1)
            result = store.import_voices({'schema': 'local-voice-studio.voices.v1', 'voices': [good]})
            self.assertEqual(result['imported'], 1)
            self.assertEqual(store.get('voices', 'original')['name'], 'Original')
            self.assertEqual(len(store.list('voices')), 2)
            store.delete('voices', 'original')
            backup = store.empty_trash()
            self.assertTrue((Path(directory) / 'backups' / backup).is_file())
            self.assertEqual(store.list('voices', trash=True), [])

    def test_restart_restore_delete_backup_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.put('voices', 'v', {'id': 'v', 'name': 'fixture', 'transcript': 'Test'}, fixture())
            store.put('draft', 'current', {'revision': 1, 'text': 'draft'}, revision=0)
            with self.assertRaises(ValueError):
                store.put('draft', 'current', {'revision': 1}, revision=0)
            store.put('jobs', 'j', {'id': 'j', 'status': 'running'})
            restarted = Store(directory)
            self.assertEqual(restarted.get('voices', 'v', True), fixture())
            self.assertEqual(restarted.get('draft', 'current')['text'], 'draft')
            self.assertEqual(restarted.get('jobs', 'j')['status'], 'interrupted')
            restarted.delete('voices', 'v'); self.assertEqual(restarted.list('voices'), [])
            self.assertEqual(len(restarted.list('voices', trash=True)), 1)
            restarted.delete('voices', 'v', restore=True)
            backup = restarted.backup()
            with closing(sqlite3.connect(Path(directory) / 'backups' / backup)) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 3)

    def test_generation_completion_cancel_and_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = Studio(directory, 'http://127.0.0.1:1')
            gate = threading.Event()
            studio.engine_request = lambda *args, **kwargs: (gate.wait(2), fixture())[1]
            job = studio.generate({'text': 'Synthetic test', 'maxTokens': 10})
            with self.assertRaises(ValueError): studio.generate({'text': 'Second'})
            self.assertEqual(studio.cancel(job['id'])['status'], 'cancelling'); gate.set()
            for _ in range(100):
                if studio.store.get('jobs', job['id'])['status'] == 'cancelled': break
                time.sleep(.01)
            self.assertEqual(studio.store.get('jobs', job['id'])['status'], 'cancelled')
            self.assertIsNone(studio.store.get('jobs', job['id'], True))
            job = studio.generate({'text': 'Synthetic completion'})
            for _ in range(100):
                if studio.store.get('jobs', job['id'])['status'] == 'complete': break
                time.sleep(.01)
            self.assertEqual(studio.store.get('jobs', job['id'], True), fixture())

    def test_loopback_origin_traversal_missing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = Studio(directory, 'http://127.0.0.1:1')
            with self.assertRaises(ValueError): Studio(directory, 'https://example.com')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(studio))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            root = f'http://127.0.0.1:{server.server_port}'
            try:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(root + '/api/draft', headers={'Origin': 'http://evil.example'}))
                self.assertEqual(caught.exception.code, 403)
                with self.assertRaises(HTTPError) as caught: urlopen(root + '/../../server.py')
                self.assertEqual(caught.exception.code, 404)
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(root + '/api/transcribe', data=fixture(), method='POST'))
                self.assertEqual(caught.exception.code, 400)
            finally: server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
