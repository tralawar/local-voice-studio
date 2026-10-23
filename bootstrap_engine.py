"""Optional Windows/NVIDIA engine setup. Never accepts license terms for the operator."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, help='Reuse an existing GGUF without downloading or moving it')
    parser.add_argument('--build', action='store_true', help='Build the bundled audio.cpp engine using official Windows script')
    parser.add_argument('--source-dir', type=Path, default=SOURCE, help='Pinned audio.cpp checkout; required when using the standalone UI source archive')
    parser.add_argument('--cuda-root', type=Path, help='Existing complete CUDA toolkit root; no global environment changes')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('Invalid port')
    model = args.model
    if not model or not model.is_file(): parser.error('Supply --model with an existing GGUF acquired under your applicable license. This release never downloads Drama weights.')
    output = ROOT / 'engine-config.local.json'
    if output.exists():
        raise SystemExit('engine-config.local.json already exists; preserve it or choose a new checkout before configuring again.')
    if args.build:
        if sys.platform != 'win32': parser.error('This bootstrap targets Windows/NVIDIA. Use upstream build instructions for other platforms.')
        source_dir = args.source_dir.resolve()
        build_script = source_dir / 'scripts/build_windows.ps1'
        if not build_script.is_file(): parser.error('--source-dir must point to the pinned audio.cpp source checkout. See RELEASE.md.')
        environment = os.environ.copy()
        if args.cuda_root:
            environment['CUDA_PATH'] = environment['CUDAToolkit_ROOT'] = str(args.cuda_root.resolve())
        subprocess.run(['powershell', '-File', str(build_script), '-Preset', 'windows-cuda-release',
                        '-ModelSet', 'custom', '-Models', 'fish_drama3', '-Target', 'audiocpp_server', '-Jobs', '8'],
                       cwd=source_dir, env=environment, check=True)
    config = json.loads((ROOT / 'engine-config.example.json').read_text())
    config['port'] = args.port
    config['models'][0]['path'] = str(model.resolve())
    output.write_text(json.dumps(config, indent=2))
    print('Configured without changing or copying the selected model. Run:')
    print(f'"{args.source_dir.resolve() / "build/windows-cuda-release/bin/audiocpp_server.exe"}" --config "{output}"')
    print(f'python run.py --engine http://127.0.0.1:{args.port}')


if __name__ == '__main__': main()
