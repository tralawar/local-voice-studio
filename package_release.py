"""Build an allowlisted, source-only standalone UI archive. Never includes engine/model/user files."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = (
    'LICENSE', 'NOTICE', 'LICENSES.md', 'README.md', 'RELEASE.md', 'VALIDATION.md', '.gitignore',
    'package.json', 'package-lock.json', 'index.html', 'requirements-stt.txt',
    'requirements-stt-lock-win-py310.txt', 'dependency-licenses-win-py310.json',
    'engine-config.example.json', 'install-windows.ps1', 'launch-standalone.cmd',
    'setup.py', 'run.py', 'server.py', 'restore.py', 'standalone.py', 'windows_job.py',
    'bootstrap_engine.py', 'package_release.py', 'outputs.py', 'output_picker.py', 'windows_outputs.py',
)
EXTENSIONS = {'.js', '.css', '.mjs', '.py', '.html'}


def build(output):
    entries = [(name, ROOT / name) for name in FILES]
    for folder in ('src', 'tests'):
        entries.extend((str(path.relative_to(ROOT)).replace('\\', '/'), path)
                       for path in (ROOT / folder).rglob('*')
                       if path.is_file() and path.suffix in EXTENSIONS and '__pycache__' not in path.parts)
    names = [name for name, _ in entries]
    if len(set(names)) != len(names): raise RuntimeError('Duplicate archive entry')
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise ValueError('Release version must be numeric major.minor.patch')
    archive = output / f'local-voice-studio-{version}-source.zip'
    if archive.exists(): raise RuntimeError('Archive exists; choose a new output directory to preserve frozen releases.')
    manifest = {'version': version, 'kind': 'independent-ui-source-only', 'drama_model_download': False,
                'engine_binaries': False, 'model_weights': False, 'user_data': False, 'files': {}}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, path in sorted(entries):
            payload = path.read_bytes()
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 22, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, payload)
            manifest['files'][name] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    manifest['archive'] = {'filename': archive.name, 'bytes': archive.stat().st_size,
                           'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    # Verify delivered bytes, rather than Git line-ending representations.
    with zipfile.ZipFile(archive) as package:
        assert sorted(package.namelist()) == sorted(manifest['files'])
        for name, info in manifest['files'].items():
            assert hashlib.sha256(package.read(name)).hexdigest() == info['sha256']
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(f"{manifest['archive']['sha256']}  {archive.name}\n", encoding='utf-8')
    print(json.dumps(manifest['archive']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output.resolve())
