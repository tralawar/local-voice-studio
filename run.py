"""Start the workspace, preferring its isolated STT environment."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
root = Path(__file__).resolve().parent
arguments = sys.argv[1:]
if '--pinokio-engine' in arguments:
    index = arguments.index('--pinokio-engine')
    name = arguments[index + 1]
    del arguments[index:index + 2]
    pterm = shutil.which('pterm.cmd' if sys.platform == 'win32' else 'pterm')
    if not pterm:
        config = json.loads((Path.home() / '.pinokio/config.json').read_text())
        pterm = str(Path(config['home']) / 'bin/npm' / ('pterm.cmd' if sys.platform == 'win32' else 'bin/pterm'))
    state = json.loads(subprocess.check_output([pterm, 'status', name, '--probe'], text=True))
    if not state.get('ready'):
        subprocess.run([pterm, 'run', state.get('ref') or name, '--default', 'start.js'], check=True)
        for attempt in range(90):
            time.sleep(2)
            state = json.loads(subprocess.check_output([pterm, 'status', name, '--probe'], text=True))
            if state.get('ready'): break
    if not state.get('ready_url') or not state.get('ready'): raise SystemExit('Local Drama engine did not become ready. Check its Pinokio logs.')
    arguments += ['--engine', state['ready_url']]
python = root / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
raise SystemExit(subprocess.call([str(python) if python.is_file() else sys.executable, str(root / 'server.py'), *arguments], cwd=root))
