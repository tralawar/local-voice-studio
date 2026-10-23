"""Isolated native-browser API regression, never uses a real microphone/profile."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import html
import json
import re
import subprocess
import tempfile
import threading
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_job import WindowsJob

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--browser', type=Path, default=Path('C:/Program Files/Google/Chrome/Application/chrome.exe'))
parser.add_argument('--observe', action='store_true', help='Record the old-code reproduction without asserting success')
args = parser.parse_args()
received = []; ready = threading.Event()
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        if self.path != '/__dictation_test_result': self.send_error(404); return
        size = int(self.headers.get('Content-Length', 0))
        if not 0 < size < 10000: self.send_error(400); return
        received.append(json.loads(self.rfile.read(size)))
        self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers(); ready.set()
server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(root)))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='synthetic-dictation-browser-') as directory:
        command = [str(args.browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                   '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions',
                   '--user-data-dir=' + directory, '--autoplay-policy=no-user-gesture-required', '--virtual-time-budget=1500',
                   '--dump-dom', f'http://127.0.0.1:{server.server_port}/tests/browser_dictation.html']
        # Capture to a file and contain all Chromium children. A pipe retained by
        # a renderer must not hang communicate() after the main browser exits.
        job = WindowsJob()
        capture = Path(directory) / 'browser-output.txt'
        try:
            with capture.open('wb') as log:
                process = job.spawn(command, cwd=root, env=os.environ.copy(), stdout=log)
                if not ready.wait(25): raise RuntimeError('Native browser did not report its synthetic capture result')
        finally: job.close()
        result = received[0]
        print(json.dumps(result))
        if not args.observe:
            assert result.get('started') and result.get('stopReturned') and result.get('trackReleased') and result.get('sessionReleased'), result
            assert not result.get('recording') and not result.get('startError') and not result.get('stopError')
finally:
    server.shutdown(); server.server_close()
