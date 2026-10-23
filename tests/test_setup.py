import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup
import bootstrap_engine


class Response(io.BytesIO):
    status = 200


class DownloadTests(unittest.TestCase):
    def test_existing_verified_model_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = {}
            for filename in setup.FILES:
                payload = ('synthetic-' + filename).encode()
                (root / filename).write_bytes(payload)
                hashes[filename] = hashlib.sha256(payload).hexdigest()
            with mock.patch.object(setup, 'HASHES', hashes), mock.patch.object(setup, 'urlopen', side_effect=AssertionError('No network permitted')):
                result = setup.download_stt(root)
            self.assertEqual(result['files'].keys(), hashes.keys())
            self.assertEqual(json.loads((root / 'download-manifest.json').read_text())['revision'], setup.REVISION)

    def test_checksum_failure_does_not_promote_partial_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(setup, 'urlopen', return_value=Response(b'corrupt synthetic download')):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    setup.download_stt(root)
            self.assertFalse((root / setup.FILES[0]).exists())
            self.assertTrue((root / (setup.FILES[0] + '.partial')).exists())

    def test_partial_resume_hashes_existing_prefix_and_new_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'model.bin.partial').write_bytes(b'first-')
            reply = Response(b'second'); reply.status = 206
            expected = hashlib.sha256(b'first-second').hexdigest()
            with mock.patch.object(setup, 'FILES', ('model.bin',)), mock.patch.object(setup, 'HASHES', {'model.bin': expected}), mock.patch.object(setup, 'urlopen', return_value=reply) as fetch:
                setup.download_stt(root)
            self.assertEqual(fetch.call_args.args[0].get_header('Range'), 'bytes=6-')
            self.assertEqual((root / 'model.bin').read_bytes(), b'first-second')
            self.assertFalse((root / 'model.bin.partial').exists())


class EngineBootstrapTests(unittest.TestCase):
    def test_existing_configuration_refuses_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'model.gguf').write_bytes(b'synthetic')
            (root / 'engine-config.local.json').write_text('preserve me')
            with mock.patch.object(bootstrap_engine, 'ROOT', root), mock.patch.object(sys, 'argv', ['bootstrap_engine.py', '--build', '--model', str(root / 'model.gguf')]), mock.patch.object(bootstrap_engine.subprocess, 'run') as build:
                with self.assertRaisesRegex(SystemExit, 'already exists'): bootstrap_engine.main()
                build.assert_not_called()
            self.assertEqual((root / 'engine-config.local.json').read_text(), 'preserve me')

    def test_standalone_archive_can_build_from_explicit_separate_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source with spaces'; (source / 'scripts').mkdir(parents=True)
            (source / 'scripts/build_windows.ps1').write_text('# synthetic, never executed')
            (root / 'model.gguf').write_bytes(b'synthetic')
            (root / 'engine-config.example.json').write_text('{"models":[{}]}')
            argv = ['bootstrap_engine.py', '--build', '--source-dir', str(source), '--model', str(root / 'model.gguf')]
            with mock.patch.object(bootstrap_engine, 'ROOT', root), mock.patch.object(sys, 'platform', 'win32'), mock.patch.object(sys, 'argv', argv), mock.patch.object(bootstrap_engine.subprocess, 'run') as build:
                bootstrap_engine.main()
                self.assertEqual(build.call_args.kwargs['cwd'], source)
                self.assertEqual(build.call_args.args[0][2], str(source / 'scripts/build_windows.ps1'))
            self.assertEqual(json.loads((root / 'engine-config.local.json').read_text())['models'][0]['path'], str(root / 'model.gguf'))


if __name__ == '__main__': unittest.main()
