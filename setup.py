"""Reproducible frontend/STT setup. Never downloads Drama weights implicitly."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parent
REPO = 'Systran/faster-whisper-tiny.en'
REVISION = '0d3d19a32d3338f10357c0889762bd8d64bbdeba'
FILES = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')
HASHES = {
    'config.json': '14b1b421a90349bc551b881461426b561a874049cb9e4c4864f2ca384f6a7cc5',
    'model.bin': '1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a',
    'tokenizer.json': '929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df',
    'vocabulary.txt': 'ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf',
}


def download_stt(destination):
    revision = REVISION
    print(f'Optional English dictation: {REPO}@{revision}; approximately 78.1 MB; MIT.', flush=True)
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < 160 * 1024 * 1024:
        raise RuntimeError('At least 160 MB free space is required for the optional STT model.')
    manifest = {'repo': REPO, 'revision': revision, 'license': 'MIT', 'files': {}}
    for filename in FILES:
        target = destination / filename
        part = destination / (filename + '.partial')
        url = f'https://huggingface.co/{REPO}/resolve/{revision}/{filename}'
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == HASHES[filename]:
            manifest['files'][filename] = {'bytes': target.stat().st_size, 'sha256': HASHES[filename]}
            print(f'{filename}: verified existing file', flush=True)
            continue
        offset = part.stat().st_size if part.exists() else 0
        request = Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        response = urlopen(request, timeout=90)
        append = offset > 0 and response.status == 206
        digest, count = hashlib.sha256(), offset if append else 0
        if append:
            with part.open('rb') as previous:
                while block := previous.read(1024 * 1024): digest.update(block)
        with response, part.open('ab' if append else 'wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block); digest.update(block); count += len(block)
                print(f'{filename}: {count / 1e6:.1f} MB', flush=True)
        if digest.hexdigest() != HASHES[filename]:
            raise RuntimeError(f'{filename}: checksum mismatch. Remove its .partial file and retry.')
        part.replace(target)
        manifest['files'][filename] = {'bytes': count, 'sha256': digest.hexdigest()}
    (destination / 'download-manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-stt', action='store_true', help='Install optional CPU STT dependencies and download 78.1 MB MIT English model')
    parser.add_argument('--stt-only', action='store_true')
    parser.add_argument('--model-dir', type=Path, default=ROOT / 'models' / 'whisper-tiny.en')
    args = parser.parse_args()
    if not args.stt_only:
        node = shutil.which('node')
        npm = shutil.which('npm.cmd' if sys.platform == 'win32' else 'npm')
        if not node or not npm:
            raise SystemExit('Node.js 22+ and npm are required for setup. Normal operation needs only Python.')
        version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
        parts = tuple(int(value) for value in version.split('.')[:2])
        if parts < (22, 12):
            raise SystemExit('Node.js 22.12+ is required for the locked Vite build. Install a supported Node.js LTS release.')
        subprocess.run([npm, 'ci', '--no-audit', '--no-fund', '--offline=false'], cwd=ROOT, check=True)
        # Direct invocation avoids user-specific npm script-shell settings.
        subprocess.run([node, str(ROOT / 'node_modules/vite/bin/vite.js'), 'build'], cwd=ROOT, check=True)
        notices = ROOT / 'dist' / 'licenses'
        notices.mkdir(exist_ok=True)
        for package in ('harper.js', 'fflate'):
            source = ROOT / 'node_modules' / package / 'LICENSE'
            if not source.exists(): source = source.with_name('LICENSE.txt')
            if source.exists(): shutil.copyfile(source, notices / (package + '.txt'))
    if args.with_stt:
        import venv
        environment = ROOT / '.venv'
        python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        if not python.is_file(): venv.create(environment, with_pip=True)
        requirements = ROOT / ('requirements-stt-lock-win-py310.txt' if sys.platform == 'win32' and sys.version_info[:2] == (3, 10) else 'requirements-stt.txt')
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        download_stt(args.model_dir)
    print('Setup complete. Configure standalone.py and open launch-standalone.cmd, or run.py --engine <loopback-engine-url>.', flush=True)


if __name__ == '__main__':
    main()
