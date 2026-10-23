import hashlib
import os
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import subprocess
from unittest import mock
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Studio, handler_for
from outputs import Outputs, approved_folder, atomic_write, take_filename, validate_filename
from test_server import fixture


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'selected output'; self.folder.mkdir()
        self.studio = Studio(self.root / 'data', 'http://127.0.0.1:1')
        self.outputs = self.studio.outputs
        self.outputs.picker = lambda *args: str(self.folder)

    def job(self, identity='synthetic', **extra):
        value = {'id': identity, 'created': 1792700000, 'status': 'complete', 'text': 'Synthetic fixture', **extra}
        self.studio.store.put('jobs', identity, value, fixture())
        return value

    def test_native_selection_persists_and_cancellation_preserves_previous_choice(self):
        self.outputs.choose()
        reloaded = Outputs(self.studio.store)
        self.assertEqual(reloaded.preferences()['folder'], str(self.folder))
        self.outputs.picker = lambda *args: None
        self.assertTrue(self.outputs.choose()['cancelled'])
        self.assertEqual(self.outputs.preferences()['folder'], str(self.folder))
        self.outputs.clear()
        self.assertIsNone(Outputs(self.studio.store).folder())

    def test_generation_auto_saves_new_completion_and_clear_never_bulk_exports(self):
        self.job('old')
        self.outputs.choose()
        self.assertEqual(list(self.folder.iterdir()), [])
        self.studio.engine_request = lambda *args, **kwargs: fixture()
        job = self.studio.generate({'text': 'Synthetic new completion'})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = self.studio.store.get('jobs', job['id'])
            if saved.get('export', {}).get('status') == 'saved': break
            time.sleep(.01)
        self.assertEqual(saved['status'], 'complete')
        self.assertEqual(saved['export']['status'], 'saved')
        self.assertEqual((self.folder / saved['export']['filename']).read_bytes(), fixture())
        self.assertEqual(len(list(self.folder.iterdir())), 1)
        self.outputs.clear()
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_collision_creates_new_filename_and_retry_is_idempotent(self):
        job = self.job(); self.outputs.choose()
        existing = self.folder / take_filename(job); existing.write_bytes(b'keep this existing file')
        result = self.outputs.export(job['id'])
        self.assertEqual(result['status'], 'saved')
        self.assertNotEqual(result['filename'], existing.name)
        self.assertEqual(existing.read_bytes(), b'keep this existing file')
        self.assertEqual(self.outputs.export(job['id'])['filename'], result['filename'])
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_missing_folder_keeps_completed_history_and_retry_uses_reselected_folder(self):
        job = self.job(); self.outputs.choose(); self.folder.rmdir()
        result = self.outputs.export(job['id'])
        self.assertEqual(result['status'], 'error'); self.assertIn('safe in history', result['error'])
        self.assertEqual(self.studio.store.get('jobs', job['id'])['status'], 'complete')
        self.assertEqual(self.studio.store.get('jobs', job['id'], True), fixture())
        self.folder.mkdir(); self.outputs.choose()
        self.assertEqual(self.outputs.export(job['id'])['status'], 'saved')

    def test_disk_full_or_permission_failure_keeps_history_and_no_partial_target(self):
        job = self.job(); self.outputs.choose()
        for error in (PermissionError('read-only disk'), OSError(28, 'Disk full')):
            with mock.patch('outputs.os.fsync', side_effect=error):
                result = self.outputs.export(job['id'])
            self.assertEqual(result['status'], 'error')
            self.assertEqual(list(self.folder.iterdir()), [])
            self.assertEqual(self.studio.store.get('jobs', job['id'], True), fixture())

    def test_restart_marks_interrupted_export_without_automatic_retry_then_recovers_published_file(self):
        job = self.job(); self.outputs.choose(); folder = self.outputs.folder()
        filename = take_filename(job)
        self.outputs._save_result(job['id'], {'status': 'saving', 'filename': filename, 'folder_id': folder['id']})
        atomic_write(folder, filename, fixture())  # Simulated abrupt exit after publish/before status acknowledgment.
        restarted = Outputs(self.studio.store)
        self.assertEqual(self.studio.store.get('jobs', job['id'])['export']['status'], 'interrupted')
        self.assertEqual(len(list(self.folder.iterdir())), 1)
        self.assertEqual(restarted.export(job['id'])['filename'], filename)
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_save_as_cancel_collision_and_explicit_native_destination(self):
        job = self.job(); self.outputs.choose()
        original = self.outputs.folder()
        self.outputs.picker = lambda *args: None
        self.assertTrue(self.outputs.save_as(job['id'])['cancelled'])
        file = self.folder / 'custom name.wav'; file.write_bytes(b'existing')
        self.outputs.picker = lambda *args: str(file)
        with self.assertRaisesRegex(ValueError, 'Nothing was overwritten'): self.outputs.save_as(job['id'])
        self.assertEqual(file.read_bytes(), b'existing')
        new = self.folder / 'another name.wav'; self.outputs.picker = lambda *args: str(new)
        result = self.outputs.save_as(job['id'])
        self.assertEqual(result['filename'], new.name); self.assertEqual(new.read_bytes(), fixture())
        self.assertEqual(self.outputs.folder(), original, 'Save as must not change the automatic output folder')

    def test_filename_sanitization_and_reserved_names(self):
        value = take_filename({'id': '../../CON:<private>?', 'created': 1792700000})
        self.assertNotIn('/', value); validate_filename(value)
        for name in ('../escape.wav', 'CON.wav', 'LPT1.wav', 'bad:stream.wav', 'trailing.wav ', 'file.mp3'):
            with self.assertRaises(ValueError): validate_filename(name)

    def test_cancelled_failed_and_interrupted_takes_do_not_export(self):
        self.outputs.choose()
        for state in ('cancelled', 'failed', 'interrupted'):
            job = self.job(state, status=state)
            with self.assertRaises(ValueError): self.outputs.export(job['id'])
        self.assertEqual(list(self.folder.iterdir()), [])
        gate = threading.Event()
        self.studio.engine_request = lambda *args, **kwargs: (gate.wait(3), fixture())[1]
        job = self.studio.generate({'text': 'Synthetic cancelled generation'})
        self.studio.cancel(job['id']); gate.set()
        deadline = time.monotonic() + 5
        while self.studio.generation_lock.locked() and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(self.studio.store.get('jobs', job['id'])['status'], 'cancelled')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_export_status_update_never_resurrects_trashed_history(self):
        job = self.job(); self.studio.store.delete('jobs', job['id'])
        with self.assertRaises(KeyError): self.outputs._save_result(job['id'], {'status': 'saved'})
        self.assertEqual(len(self.studio.store.list('jobs', trash=True)), 1)
        self.assertEqual(self.studio.store.list('jobs'), [])

    def test_replaced_folder_requires_new_explicit_selection(self):
        job = self.job(); self.outputs.choose()
        moved = self.root / 'moved'; self.folder.rename(moved); self.folder.mkdir()
        result = self.outputs.export(job['id'])
        self.assertEqual(result['status'], 'error'); self.assertIn('replaced', result['error'])
        self.assertEqual(list(self.folder.iterdir()), [])
        self.outputs.choose()
        self.assertEqual(self.outputs.export(job['id'])['status'], 'saved')

    def test_simultaneous_atomic_publish_never_overwrites_winner(self):
        folder = approved_folder(self.folder); results = []; gate = threading.Barrier(2)
        def write(payload):
            gate.wait()
            try: atomic_write(folder, 'same.wav', payload); results.append(('saved', payload))
            except FileExistsError: results.append(('exists', payload))
        threads = [threading.Thread(target=write, args=(payload,)) for payload in (b'synthetic A', b'synthetic B')]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertEqual(sorted(state for state, _ in results), ['exists', 'saved'])
        self.assertEqual((self.folder / 'same.wav').read_bytes(), next(payload for state, payload in results if state == 'saved'))
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_external_failure_never_changes_successful_generation_to_failed(self):
        self.outputs.choose()
        self.studio.engine_request = lambda *args, **kwargs: fixture()
        with mock.patch('outputs.atomic_write', side_effect=OSError(28, 'Disk full')):
            job = self.studio.generate({'text': 'Synthetic generation with unavailable external disk'})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                saved = self.studio.store.get('jobs', job['id'])
                if saved.get('export', {}).get('status') == 'error': break
                time.sleep(.01)
        self.assertEqual(saved['status'], 'complete'); self.assertEqual(saved['export']['status'], 'error')
        self.assertEqual(self.studio.store.get('jobs', job['id'], True), fixture())

    def test_api_rejects_remote_paths_missing_token_origin_and_alias_routes(self):
        static = self.root / 'static'; static.mkdir()
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.studio, static))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with urlopen(origin + '/api/output-folder') as response: preferences = json.load(response)
        def post(path, body, headers):
            request = Request(origin + path, json.dumps(body).encode(), headers={'Content-Type': 'application/json', **headers})
            try:
                with urlopen(request) as response: return response.status, json.load(response)
            except HTTPError as error: return error.code, json.load(error)
        valid = {'Origin': origin, 'X-Output-Token': preferences['action_token']}
        with mock.patch.object(self.outputs, 'picker', return_value=str(self.folder)) as picker:
            self.assertEqual(post('/api/output-folder/choose', {}, {})[0], 403)
            self.assertEqual(post('/api/output-folder/choose', {}, {**valid, 'Origin': 'https://evil.invalid'})[0], 403)
            self.assertEqual(post('/api/output-folder/choose', {'path': str(self.folder)}, valid)[0], 400)
            self.assertEqual(post('/other/history/a/save-as', {}, {})[0], 404)
            picker.assert_not_called()
            self.assertEqual(post('/api/output-folder/choose', {}, valid)[0], 200)
            picker.assert_called_once()

    def test_slash_variants_authorize_at_dispatch_before_picker_or_export(self):
        self.job('synthetic')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.studio, self.root))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        def post(action, suffix, headers):
            request = Request(origin + '/api/history/synthetic/' + action + suffix, b'{}', headers={'Content-Type': 'application/json', **headers})
            try:
                with urlopen(request) as response: return response.status
            except HTTPError as error: return error.code
        valid = {'Origin': origin, 'X-Output-Token': self.outputs.token}
        with mock.patch.object(self.outputs, 'save_as', return_value={'status': 'saved'}) as picker, mock.patch.object(self.outputs, 'export', return_value={'status': 'saved'}) as export:
            for action in ('save-as', 'export'):
                for suffix in ('', '/', '///'):
                    for headers in ({}, {'Origin': origin}, {'X-Output-Token': self.outputs.token}):
                        self.assertEqual(post(action, suffix, headers), 403)
            picker.assert_not_called(); export.assert_not_called()
            for action in ('save-as', 'export'):
                for suffix in ('', '/', '///'): self.assertEqual(post(action, suffix, valid), 200)
            self.assertEqual(picker.call_count, 3); self.assertEqual(export.call_count, 3)

    @unittest.skipUnless(os.name == 'nt', 'Windows directory/file handle protection')
    def test_directory_and_staging_substitution_are_blocked_during_publication(self):
        import windows_outputs
        folder = approved_folder(self.folder); publish = windows_outputs.publish; blocked = []
        def substitute(root, source, name):
            with self.assertRaises(PermissionError): self.folder.rename(self.root / 'moved')
            blocked.append('directory')
            temporary = next(self.folder.glob('.localvoice-*.partial'))
            with self.assertRaises(PermissionError): temporary.unlink()
            with self.assertRaises(PermissionError): temporary.write_bytes(b'RIFF replacement content')
            blocked.append('staging')
            return publish(root, source, name)
        with mock.patch('windows_outputs.publish', side_effect=substitute):
            saved = atomic_write(folder, 'synthetic.wav', fixture())
        self.assertEqual(blocked, ['directory', 'staging'])
        self.assertEqual(saved.read_bytes(), fixture())
        self.assertEqual(self.folder.stat().st_ino, folder['inode'])
        self.assertEqual(list(self.folder.glob('*.partial')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows handle identity validation')
    def test_replacement_between_path_check_and_directory_open_never_receives_bytes(self):
        import windows_outputs
        folder = approved_folder(self.folder); kernel, _ = windows_outputs.api()
        create = kernel.CreateFileW
        def substitute(*args):
            self.folder.rename(self.root / 'original-folder'); self.folder.mkdir()
            return create(*args)
        with mock.patch.object(kernel, 'CreateFileW', side_effect=substitute):
            with self.assertRaisesRegex(ValueError, 'replaced'): atomic_write(folder, 'synthetic.wav', fixture())
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(list((self.root / 'original-folder').iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction handling')
    def test_native_open_reparse_point_rejects_junction_even_after_path_check(self):
        import windows_outputs
        folder = approved_folder(self.folder)
        target = self.root / 'original'; self.folder.rename(target)
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(self.folder), str(target)], capture_output=True, text=True)
        if result.returncode: self.skipTest('Windows could not create isolated junction fixture: ' + result.stderr)
        try:
            # Force the precise race boundary: path check already passed before junction substitution.
            with mock.patch('outputs.check_folder', return_value=self.folder):
                with self.assertRaisesRegex(ValueError, 'Reparse'): atomic_write(folder, 'synthetic.wav', fixture())
            self.assertEqual(list(target.iterdir()), [])
        finally: self.folder.rmdir()  # Removes only the verified temporary junction, never its target tree.


if __name__ == '__main__': unittest.main()
