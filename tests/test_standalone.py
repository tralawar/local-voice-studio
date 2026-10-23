import hashlib
import json
from pathlib import Path
import sys
import tempfile
import socket
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import standalone


class StandaloneTests(unittest.TestCase):
    def test_occupied_ui_port_fails_before_any_owned_process_is_created(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0)); occupied.listen()
            args = SimpleNamespace(verify_only=False, ui_port=occupied.getsockname()[1])
            with mock.patch.object(standalone, 'ROOT', Path(directory)), mock.patch.object(standalone, 'WindowsJob') as create_job:
                with self.assertRaisesRegex(RuntimeError, 'already in use'):
                    standalone.run_processes(args, {}, Path('unused.exe'), Path('unused.gguf'), Path('unused'), [])
                create_job.assert_not_called()
            with socket.create_connection(occupied.getsockname(), timeout=1): pass

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Job Object lifetime test')
    def test_abrupt_synthetic_supervisor_exit_kills_only_its_owned_listeners(self):
        import ctypes as C
        from ctypes import wintypes as W
        from windows_job import kernel
        api = kernel(); api.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; api.OpenProcess.restype = W.HANDLE
        handles = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / 'supervisor.log').open('wb') as log:
                owner = subprocess.Popen([sys.executable, str(Path(__file__).with_name('job_supervisor_fixture.py')), directory], stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline = time.monotonic() + 15
                    while not (root / 'ready.json').exists():
                        if owner.poll() is not None:
                            self.fail('Synthetic owner exited: ' + (root / 'supervisor.log').read_text(errors='replace'))
                        if time.monotonic() > deadline: self.fail('Synthetic owner readiness timed out')
                        time.sleep(.02)
                    proof = json.loads((root / 'ready.json').read_text())
                    self.assertEqual(proof['owner'], owner.pid)
                    for child in proof['children']:
                        self.assertNotEqual(child['pid'], 55340)
                        handle = api.OpenProcess(0x00100000 | 0x1000 | 1, False, child['pid'])
                        self.assertTrue(handle); handles.append(handle)
                        with socket.create_connection(('127.0.0.1', child['port']), timeout=1): pass
                    owner.terminate(); owner.wait(10)  # Exact disposable process handle; no PID-wide kill.
                    for handle in handles: self.assertEqual(api.WaitForSingleObject(handle, 10000), 0)
                    for child in proof['children']:
                        with socket.socket() as probe:
                            self.assertNotEqual(probe.connect_ex(('127.0.0.1', child['port'])), 0)
                finally:
                    if owner.poll() is None: owner.terminate(); owner.wait(10)
                    for handle in handles:
                        # Failure cleanup is limited to the exact synthetic handles opened above.
                        if api.WaitForSingleObject(handle, 0) == 258: api.TerminateProcess(handle, 1); api.WaitForSingleObject(handle, 10000)
                        api.CloseHandle(handle)

    def test_existing_engine_blocks_launch_without_spawning_or_stopping_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); engine = root / 'synthetic.exe'; engine.write_bytes(b'synthetic-not-executable')
            model = root / 'synthetic.gguf'; model.write_bytes(b'synthetic-not-weights')
            static = root / 'static'; static.mkdir(); (static / 'index.html').write_text('Synthetic')
            settings = root / 'standalone.local.json'; settings.write_text(json.dumps({'engine_exe':str(engine), 'engine_sha256':standalone.digest(engine), 'model':str(model), 'static':str(static)}))
            with mock.patch.object(standalone, 'ROOT', root), mock.patch.object(standalone, 'SETTINGS', settings), \
                 mock.patch.object(standalone.sys, 'platform', 'win32'), mock.patch.object(standalone.sys, 'argv', ['standalone.py']), \
                 mock.patch.object(standalone, 'other_engines', return_value=[98765]), mock.patch.object(standalone, 'WindowsJob') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'Another native speech engine is running'):
                    standalone.main()
                spawn.assert_not_called()

    def test_configure_copies_engine_only_and_reuses_model_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'existing.exe'; source.write_bytes(b'synthetic-not-executable')
            model = root / 'existing.gguf'; model.write_bytes(b'synthetic-not-weights')
            settings = root / 'standalone.local.json'
            with mock.patch.object(standalone, 'ROOT', root), mock.patch.object(standalone, 'SETTINGS', settings), \
                 mock.patch.object(standalone.sys, 'platform', 'win32'), mock.patch.object(standalone.sys, 'argv', ['standalone.py','--configure','--engine-exe',str(source),'--model',str(model)]):
                standalone.main()
            data = json.loads(settings.read_text())
            self.assertEqual(Path(data['model']), model.resolve())
            self.assertEqual((root / '.native/audiocpp_server.exe').read_bytes(), source.read_bytes())
            self.assertEqual(len(list(root.rglob('*.gguf'))), 1)


if __name__ == '__main__': unittest.main()
