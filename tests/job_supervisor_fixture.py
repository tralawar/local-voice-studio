"""Disposable synthetic listener children for the abrupt-owner-exit test only."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_job import WindowsJob
root = Path(sys.argv[1]); job = WindowsJob()
listener = """import json,os,socket,sys,time
from pathlib import Path
s=socket.socket();s.bind(('127.0.0.1',0));s.listen()
Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}))
while True:time.sleep(1)
"""
with (root / 'children.log').open('ab') as log:
    for index in range(2):
        job.spawn([sys.executable, '-u', '-c', listener, str(root / f'child-{index}.json')], cwd=root, env=os.environ.copy(), stdout=log)
    deadline = time.monotonic() + 15
    while not all((root / f'child-{index}.json').exists() for index in range(2)):
        if time.monotonic() > deadline: raise RuntimeError('Synthetic listeners did not start')
        time.sleep(.02)
    children = [json.loads((root / f'child-{index}.json').read_text()) for index in range(2)]
    (root / 'ready.json').write_text(json.dumps({'owner': os.getpid(), 'children': children}))
    # Intentionally no finally/atexit cleanup: the test terminates this process.
    while True: time.sleep(1)
