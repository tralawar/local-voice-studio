"""Operator-only database restore. Stop the workspace before running."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from server import Store, exclusive_data_lock
parser = argparse.ArgumentParser()
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--backup', required=True, help='A filename within this data directory/backups')
args = parser.parse_args()
root = args.data.resolve()
source = (root / 'backups' / args.backup).resolve()
if source.parent != root / 'backups' or not source.is_file():
    raise SystemExit('Choose an existing snapshot filename inside data/backups.')
with exclusive_data_lock(root):
    with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as backup:
        if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise SystemExit('Backup integrity check failed.')
        if backup.execute("SELECT value FROM metadata WHERE key='schema'").fetchone() != ('1',): raise SystemExit('Unsupported database schema.')
        store = Store(root)
        recovery = store.backup()
        with store.connect() as current: backup.backup(current)
print(f'Restored {source.name}. Previous data preserved in {recovery}.')
