import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from backend.platform_backup import FILES,extract,verified


class BackupArchiveTests(unittest.TestCase):
    def test_corrupted_file_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for name in FILES: (folder/name).write_bytes(b'retained fixture')
            manifest={'format':1,'sha256':{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in FILES}}
            (folder/'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(verified(folder),manifest)
            (folder/'database.dump').write_bytes(b'changed')
            with self.assertRaises(ValueError): verified(folder)

    def test_unexpected_manifest_files_cannot_select_other_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); (folder/'manifest.json').write_text(json.dumps({'format':1,'sha256':{'../outside':'a'*64}}))
            with self.assertRaises(ValueError): verified(folder)

    def test_archive_traversal_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for i,name in enumerate(('../escape','/absolute','link')):
                archive=folder/(str(i)+'.tar')
                with tarfile.open(archive,'w') as stream:
                    info=tarfile.TarInfo(name)
                    if name=='link': info.type=tarfile.SYMTYPE; info.linkname='../escape'
                    stream.addfile(info,io.BytesIO())
                with self.assertRaises(ValueError): extract(archive,folder/('destination'+str(i)))
