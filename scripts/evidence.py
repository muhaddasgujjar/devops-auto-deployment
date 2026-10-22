"""Immutable local evidence catalogue, checksum verification, and portable backups."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from scripts.render_release import ROOT

DEFAULT_STORE = Path(os.environ.get('RELEASE_EVIDENCE_DIR', '/var/lib/release-lab/evidence'))
NAMES = {'summary.json', 'source.json', 'image.json', 'scan.json', 'sbom.json',
         'rollout.json', 'analysisrun.json', 'service.json', 'pod.json', 'event.json',
         'application.json', 'jenkins-build.json', 'environment-commit.json', 'trivy-db-metadata.json'}
NAMES.update({'prometheus-before.json', 'prometheus-after.json', 'storage.json', 'prometheus-backup.tar.gz'})
NAMES.add('recovery.json')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class EvidenceStore:
    def __init__(self, root=DEFAULT_STORE):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / 'objects').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'catalog.sqlite3', timeout=30)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, archived_at TEXT NOT NULL, verdict TEXT NOT NULL,
            availability_failures INTEGER, manifest_sha256 TEXT NOT NULL, summary_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS files (
            run_id TEXT REFERENCES runs(id), name TEXT NOT NULL, sha256 TEXT NOT NULL,
            size INTEGER NOT NULL, PRIMARY KEY(run_id,name));
          PRAGMA user_version=1;
        ''')

    def close(self):
        self.db.close()

    def archive(self, folder, source_root=ROOT / 'output', incomplete=False):
        folder, source_root = Path(folder).resolve(), Path(source_root).resolve()
        if not folder.is_relative_to(source_root) or folder == source_root:
            raise ValueError('Only a trial directory within the evidence source root is allowed')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', folder.name):
            raise ValueError('Invalid run identifier')
        summary_path = folder / 'summary.json'
        if not summary_path.exists() and not incomplete:
            raise ValueError('Run has no final summary; explicitly mark an interrupted run incomplete')
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {'verdict': 'incomplete'}
        files = []
        for path in sorted(folder.rglob('*')):
            if not path.is_file():
                continue
            name = path.relative_to(folder).as_posix()
            accepted = (name in NAMES or re.fullmatch(r'(stable|preview-[0-9]+)\.jsonl', name)
                        or re.fullmatch(r'desired/(analysis|namespace|rollout|services)\.yaml', name))
            if not accepted:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(folder):
                raise ValueError('Evidence may not reference files outside its trial')
            before = path.stat()
            with tempfile.NamedTemporaryFile(dir=self.root / 'objects', delete=False) as stream:
                temporary = Path(stream.name)
                with path.open('rb') as source:
                    shutil.copyfileobj(source, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Evidence is still being written; archive after the trial exits')
                sha = digest(temporary)
                destination = self.root / 'objects' / sha
                if destination.exists():
                    if digest(destination) != sha:
                        raise ValueError('Existing evidence object is corrupt')
                else:
                    temporary.replace(destination)
                files.append({'name': name, 'sha256': sha, 'size': after.st_size})
            finally:
                temporary.unlink(missing_ok=True)
        fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        existing = self.db.execute('SELECT manifest_sha256 FROM runs WHERE id=?', (folder.name,)).fetchone()
        if existing:
            if existing[0] != fingerprint:
                raise ValueError('Run identifier already refers to different immutable evidence')
            self.verify(folder.name)
            return {'run_id': folder.name, 'files': len(files), 'already_archived': True}
        with self.db:
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',
                            (folder.name, datetime.now(timezone.utc).isoformat(), summary.get('verdict', 'unknown'),
                             summary.get('stable_non_200'), fingerprint, json.dumps(summary, sort_keys=True)))
            self.db.executemany('INSERT INTO files VALUES(?,?,?,?)',
                                [(folder.name, f['name'], f['sha256'], f['size']) for f in files])
        return {'run_id': folder.name, 'files': len(files), 'already_archived': False}

    def verify(self, run_id=None):
        rows = self.db.execute('SELECT run_id,name,sha256,size FROM files' + (' WHERE run_id=?' if run_id else ''),
                               (run_id,) if run_id else ()).fetchall()
        for _, _, sha, size in rows:
            if not re.fullmatch(r'[a-f0-9]{64}', sha):
                raise ValueError('Invalid evidence object identifier')
            path = self.root / 'objects' / sha
            if not path.is_file() or path.stat().st_size != size or digest(path) != sha:
                raise ValueError(f'Missing or corrupt evidence object: {sha}')
        for identifier, expected in self.db.execute('SELECT id,manifest_sha256 FROM runs' + (' WHERE id=?' if run_id else ''),
                                                   (run_id,) if run_id else ()):
            manifest = [{'name': name, 'sha256': sha, 'size': size}
                        for _, name, sha, size in sorted(r for r in rows if r[0] == identifier)]
            if hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != expected:
                raise ValueError('Evidence manifest does not match the catalogue')
        integrity = self.db.execute('PRAGMA integrity_check').fetchall()
        if integrity != [('ok',)] or self.db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Evidence catalogue integrity check failed')
        return {'verified_files': len(rows), 'integrity': 'ok'}

    def backup(self, archive):
        archive = Path(archive)
        if archive.exists():
            raise ValueError('Backup destination already exists')
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'catalog.sqlite3'
            with closing(sqlite3.connect(snapshot)) as destination:
                self.db.backup(destination)
                hashes = [row[0] for row in destination.execute('SELECT DISTINCT sha256 FROM files ORDER BY sha256')]
            with tarfile.open(archive, 'w:gz') as tar:
                tar.add(snapshot, arcname='catalog.sqlite3')
                for sha in hashes:
                    if not re.fullmatch(r'[a-f0-9]{64}', sha) or digest(self.root / 'objects' / sha) != sha:
                        raise ValueError('Refusing to back up corrupt evidence')
                    tar.add(self.root / 'objects' / sha, arcname='objects/' + sha)
        return {'archive': str(archive), 'sha256': digest(archive), 'objects': len(hashes)}


def restore(archive, target):
    target = Path(target)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError('Restore requires a new or empty directory')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if ('catalog.sqlite3' not in {m.name for m in members}
                or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or not re.fullmatch(r'catalog\.sqlite3|objects/[a-f0-9]{64}', m.name) for m in members)
                or sum(m.size for m in members) > 10 * 1024**3):
            raise ValueError('Unexpected evidence backup entries')
        tar.extractall(target, filter='data')
    store = EvidenceStore(target)
    try:
        return store.verify()
    finally:
        store.close()


def archive_run(folder):
    store = EvidenceStore()
    try:
        return store.archive(folder)
    finally:
        store.close()


def finalize_archive(folder):
    """Fail a successful command on archive failure; preserve an existing error."""
    existing_error = sys.exception()
    try:
        print('Evidence archived: ' + json.dumps(archive_run(folder)), flush=True)
    except Exception as exc:
        if existing_error is None:
            raise
        print(f'Evidence archive failed: {exc}; raw report retained at {folder}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['archive', 'list', 'verify', 'backup', 'restore'])
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--incomplete', action='store_true')
    args = parser.parse_args()
    if args.action == 'restore':
        print(json.dumps(restore(args.archive, args.store)))
        return
    store = EvidenceStore(args.store)
    try:
        if args.action == 'archive':
            result = store.archive(args.source, incomplete=args.incomplete)
        elif args.action == 'list':
            result = [dict(zip(('run_id', 'verdict', 'stable_failures'), row))
                      for row in store.db.execute('SELECT id,verdict,availability_failures FROM runs ORDER BY id')]
        elif args.action == 'backup':
            result = store.backup(args.archive)
        else:
            result = store.verify()
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == '__main__':
    main()
