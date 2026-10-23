"""Run manually against a synthetic WAV with all Python socket connections denied."""
from pathlib import Path
import json
import socket
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Studio
def denied(*args, **kwargs): raise RuntimeError('Network access disabled by offline test')
socket.socket.connect = denied
socket.create_connection = denied
root = Path(__file__).resolve().parents[1]
audio = Path(sys.argv[1]).read_bytes()
with tempfile.TemporaryDirectory() as directory:
    studio = Studio(directory, 'http://127.0.0.1:1', root / 'models/whisper-tiny.en')
    for _ in range(2): print(json.dumps(studio.transcribe(audio)))
