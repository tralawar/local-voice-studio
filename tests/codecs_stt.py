"""Optional local codec smoke; input must be an operator-selected synthetic WAV."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import av
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Studio
source = Path(sys.argv[1]).resolve()
def denied(*args, **kwargs): raise RuntimeError('Network disabled by codec test')
socket.socket.connect = denied
socket.create_connection = denied
with tempfile.TemporaryDirectory() as directory:
    app = Studio(Path(directory) / 'data', 'http://127.0.0.1:1', Path(__file__).resolve().parents[1] / 'models/whisper-tiny.en')
    for suffix, container, codec, sample_format, mime in [('webm', 'webm', 'libopus', 'flt', 'audio/webm;codecs=opus'), ('m4a', 'ipod', 'aac', 'fltp', 'audio/mp4')]:
        target = Path(directory) / ('synthetic.' + suffix)
        with av.open(str(source)) as incoming, av.open(str(target), 'w', format=container) as output:
            stream = output.add_stream(codec, rate=48000); stream.layout = 'mono'
            converter = av.AudioResampler(format=sample_format, layout='mono', rate=48000)
            for frame in incoming.decode(audio=0):
                for converted in converter.resample(frame):
                    for packet in stream.encode(converted): output.mux(packet)
            for frame in converter.resample(None):
                for packet in stream.encode(frame): output.mux(packet)
            for packet in stream.encode(None): output.mux(packet)
        result = app.transcribe(target.read_bytes(), mime)
        assert result['text'].strip(), suffix
        print(json.dumps({'codec': codec, 'decoded': True, 'elapsed': result['elapsed']}))
    try: app.transcribe(b'invalid synthetic container', 'audio/webm')
    except ValueError as error: assert 'could not be decoded' in str(error)
    else: raise AssertionError('Invalid recording was not rejected')
    print('invalid-container diagnostic PASS; no transcript/audio logged')
