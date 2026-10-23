"""User-invoked native Windows picker. Prints only the explicitly selected path."""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('folder', 'file'))
    parser.add_argument('--initial', default='')
    parser.add_argument('--name', default='take.wav')
    args = parser.parse_args()
    if sys.platform != 'win32': raise RuntimeError('Native output selection currently requires Windows. Download WAV remains available.')
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    try:
        options = {'parent': root, 'initialdir': args.initial or None}
        if args.kind == 'folder':
            selected = filedialog.askdirectory(title='Automatically save new WAV takes here', mustexist=True, **options)
        else:
            selected = filedialog.asksaveasfilename(title='Save a copy of this take (existing files are never overwritten)',
                initialfile=args.name, defaultextension='.wav', filetypes=[('WAV audio', '*.wav')], confirmoverwrite=False, **options)
        print(json.dumps({'path': selected or None}), flush=True)
    finally:
        root.destroy()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'error': 'The native file picker could not open. Check that this Windows Python installation includes Tkinter and has an interactive desktop.'}), flush=True)
        raise SystemExit(1)
