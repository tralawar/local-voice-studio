"""Windows standalone supervisor: owns both native inference and workspace processes."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser
from server import exclusive_data_lock
from windows_job import WindowsJob

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / 'standalone.local.json'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def other_engines():
    if sys.platform != 'win32': return []
    result = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq audiocpp_server.exe', '/FO', 'CSV', '/NH'], text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return [int(row[1]) for row in csv.reader(io.StringIO(result)) if len(row) > 1 and row[0].lower() == 'audiocpp_server.exe']


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); return probe.getsockname()[1]


def require_available_port(port):
    if not 1 <= port <= 65535: raise ValueError('UI port must be between 1 and 65535.')
    with socket.socket() as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'): probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try: probe.bind(('127.0.0.1', port))
        except OSError as error: raise RuntimeError(f'UI port {port} is already in use. Keep the existing app open or choose another --ui-port; nothing was stopped.') from error


def wait_json(url, process, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None: raise RuntimeError('A local process exited. Check .runtime logs; no other application was stopped.')
        try:
            with urlopen(url, timeout=2) as response: return json.load(response)
        except OSError: time.sleep(.2)
    raise RuntimeError('Local startup timed out. Check .runtime logs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--engine-exe', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--cuda-bin', type=Path)
    parser.add_argument('--static', type=Path)
    parser.add_argument('--ui-port', type=int, default=8046)
    parser.add_argument('--verify-only', action='store_true', help='Launch owned UI/engine on temporary ports without loading GPU weights, verify, then stop only those processes')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32': parser.error('This launcher targets Windows; the server.py service itself is cross-platform.')
    if args.configure:
        if not args.engine_exe or not args.engine_exe.is_file() or not args.model or not args.model.is_file():
            parser.error('Configure with an existing verified --engine-exe and --model. No model is downloaded or copied.')
        if SETTINGS.exists(): parser.error('standalone.local.json already exists; preserve it before configuring another installation.')
        native = ROOT / '.native'; native.mkdir(exist_ok=True)
        executable = native / 'audiocpp_server.exe'
        shutil.copyfile(args.engine_exe, executable)
        expected = digest(args.engine_exe)
        if digest(executable) != expected: raise RuntimeError('Native executable copy verification failed.')
        data = {'engine_exe': str(executable), 'engine_sha256': expected, 'model': str(args.model.resolve()),
                'cuda_bin': str(args.cuda_bin.resolve()) if args.cuda_bin else '', 'static': str(args.static.resolve()) if args.static else str(ROOT / 'dist')}
        SETTINGS.write_text(json.dumps(data, indent=2))
        print('Configured standalone launcher; copied only the verified executable. Model files are reused in place.')
        return
    if not SETTINGS.is_file(): parser.error('Run --configure first. See README; no Pinokio process or CLI is needed.')
    data = json.loads(SETTINGS.read_text())
    executable, model, static = Path(data['engine_exe']), Path(data['model']), args.static or Path(data['static'])
    if not executable.is_file() or digest(executable) != data['engine_sha256']: raise RuntimeError('Standalone engine executable is missing or changed. Re-verify the local installation.')
    if not model.is_file() or not (static / 'index.html').is_file(): raise RuntimeError('Existing model or built UI is missing; setup is required.')
    existing = other_engines()
    if existing and not args.verify_only:
        raise RuntimeError(f'Another native speech engine is running (PID {existing}). Finish any generation and coordinate closing it before starting standalone; no process was stopped and no second model was loaded.')
    with exclusive_data_lock(ROOT / '.runtime'):
        run_processes(args, data, executable, model, static, existing)


def run_processes(args, data, executable, model, static, existing):
    runtime = ROOT / '.runtime'; runtime.mkdir(exist_ok=True)
    engine_port = free_port()
    ui_port = free_port() if args.verify_only else args.ui_port
    while ui_port == engine_port: engine_port = free_port()
    require_available_port(ui_port)
    config = json.loads((ROOT / 'engine-config.example.json').read_text())
    config.update(port=engine_port, lazy_load=True, ui=False)
    config['models'][0]['path'] = str(model)
    config_path = runtime / 'engine.json'; config_path.write_text(json.dumps(config, indent=2))
    env = os.environ.copy()
    if data.get('cuda_bin'): env['PATH'] = data['cuda_bin'] + os.pathsep + env.get('PATH', '')
    python = ROOT / '.venv/Scripts/python.exe'
    if not python.is_file(): python = Path(sys.executable)
    children, logs, job = [], [], None
    try:
        job = WindowsJob()
        for filename in ('engine.log', 'workspace.log'): logs.append((runtime / filename).open('ab'))
        engine = job.spawn([str(executable), '--config', str(config_path)], cwd=runtime, env=env, stdout=logs[0])
        children.append(engine)
        wait_json(f'http://127.0.0.1:{engine_port}/health', engine)
        command = [str(python), str(ROOT / 'server.py'), '--engine', f'http://127.0.0.1:{engine_port}',
                   '--port', str(ui_port), '--static', str(static)]
        if args.verify_only: command += ['--data', str(runtime / 'verification-data')]
        workspace = job.spawn(command, cwd=ROOT, env=env, stdout=logs[1])
        children.append(workspace)
        state = wait_json(f'http://127.0.0.1:{ui_port}/api/status', workspace)
        with urlopen(f'http://127.0.0.1:{engine_port}/v1/models') as response: models = json.load(response)
        with urlopen(f'http://127.0.0.1:{ui_port}/') as response:
            assert response.status == 200
            html = response.read().decode('utf-8')
        proof = {'supervisor_pid': os.getpid(), 'engine_pid': engine.pid, 'workspace_pid': workspace.pid,
                 'engine_port': engine_port, 'ui_port': ui_port, 'engine_health': state['engine']['status'],
                 'stt_ready': state['stt'], 'verify_only': args.verify_only,
                 'loaded_models': sum(bool(m.get('loaded')) for m in models.get('data', [])),
                 'pinokio_calls': False, 'existing_engine_pids': existing,
                 'reference_dictation_control': 'id="voice-dictate"' in html,
                 'child_lifetime': 'Windows kill-on-close job assigned at process creation'}
        (runtime / 'standalone-verification.json').write_text(json.dumps(proof, indent=2))
        print(json.dumps(proof), flush=True)
        if args.verify_only:
            if proof['loaded_models']: raise RuntimeError('Verification unexpectedly loaded model weights; stopping owned processes.')
            return
        url = f'http://127.0.0.1:{ui_port}/'
        print(f'Standalone workspace ready: {url}\nKeep this launcher open. Ctrl+C stops only its owned processes.', flush=True)
        if args.open: webbrowser.open(url)
        while all(process.poll() is None for process in children): time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        if job: job.close()
        for log in logs: log.close()


if __name__ == '__main__':
    try: main()
    except Exception as error: print(f'Standalone startup: {error}', file=sys.stderr); raise SystemExit(1)
