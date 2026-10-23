import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.evidence import EvidenceStore, restore


class EvidenceTests(unittest.TestCase):
    def fixture(self, base):
        source = base / 'output'
        run = source / 'trial-healthy-1'
        run.mkdir(parents=True)
        (run / 'summary.json').write_text(json.dumps({'verdict': 'candidate-promoted', 'stable_non_200': 0}))
        (run / 'stable.jsonl').write_text('{"status":200}\n')
        (run / 'private.key').write_text('excluded')
        return source, run

    def test_archive_is_idempotent_and_survives_loss_of_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, run = self.fixture(base)
            store = EvidenceStore(base / 'store')
            try:
                self.assertEqual(store.archive(run, source)['files'], 2)
                self.assertTrue(store.archive(run, source)['already_archived'])
                for path in run.iterdir():
                    path.unlink()
                self.assertEqual(store.verify()['verified_files'], 2)
            finally:
                store.close()

    def test_changed_run_cannot_overwrite_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, run = self.fixture(base)
            store = EvidenceStore(base / 'store')
            try:
                store.archive(run, source)
                (run / 'stable.jsonl').write_text('{"status":500}\n')
                with self.assertRaises(ValueError):
                    store.archive(run, source)
            finally:
                store.close()

    def test_fault_snapshots_are_archived_but_console_logs_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, run = self.fixture(base)
            (run / 'analysis-observed.json').write_text('{"items":[]}')
            (run / 'telemetry-fixture.json').write_text('{"replicas":1}')
            (run / 'jenkins-console.txt').write_text('excluded')
            store = EvidenceStore(base / 'store')
            try:
                self.assertEqual(store.archive(run, source)['files'], 4)
                names = {row[0] for row in store.db.execute('SELECT name FROM files')}
                self.assertIn('analysis-observed.json', names)
                self.assertIn('telemetry-fixture.json', names)
                self.assertNotIn('jenkins-console.txt', names)
                self.assertEqual(store.verify()['verified_files'], 4)
            finally:
                store.close()

    def test_backup_restore_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, run = self.fixture(base)
            store = EvidenceStore(base / 'store')
            try:
                store.archive(run, source)
                store.backup(base / 'backup.tar.gz')
            finally:
                store.close()
            self.assertEqual(restore(base / 'backup.tar.gz', base / 'restored')['verified_files'], 2)
            next((base / 'restored/objects').iterdir()).write_bytes(b'corrupted')
            restored = EvidenceStore(base / 'restored')
            try:
                with self.assertRaises(ValueError):
                    restored.verify()
            finally:
                restored.close()

    def test_rejects_escape_and_unfinished_run(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, run = self.fixture(base)
            store = EvidenceStore(base / 'store')
            try:
                with self.assertRaises(ValueError):
                    store.archive(run, base / 'elsewhere')
                (run / 'summary.json').unlink()
                with self.assertRaises(ValueError):
                    store.archive(run, source)
                self.assertFalse(store.archive(run, source, incomplete=True)['already_archived'])
            finally:
                store.close()

    def test_restore_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with tarfile.open(base / 'bad.tar', 'w') as tar:
                entry = tarfile.TarInfo('../escaped')
                entry.size = 1
                tar.addfile(entry, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                restore(base / 'bad.tar', base / 'restored')
            self.assertFalse((base / 'escaped').exists())
            with tarfile.open(base / 'empty.tar', 'w'):
                pass
            with self.assertRaises(ValueError):
                restore(base / 'empty.tar', base / 'empty-restored')
