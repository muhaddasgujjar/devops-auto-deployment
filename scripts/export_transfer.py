"""Export committed Git history and verify a real independent clone. No runtime data."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.PIPE, timeout=180).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/transfer')
    args = parser.parse_args()
    if git('status', '--porcelain'):
        raise SystemExit('Commit reviewed changes before exporting')
    sha = git('rev-parse', 'HEAD')
    branch = git('symbolic-ref', '--short', 'HEAD')
    folder = args.output.resolve() / sha
    folder.mkdir(parents=True, exist_ok=False)
    bundle = folder / 'release-platform.bundle'
    git('bundle', 'create', str(bundle), '--all')
    git('bundle', 'verify', str(bundle))
    refs = git('for-each-ref', '--format=%(objectname) %(refname)').splitlines()
    with tempfile.TemporaryDirectory(prefix='release-transfer-') as temp:
        clone = Path(temp) / 'clone'
        git('clone', '--no-hardlinks', '--branch', branch, str(bundle), str(clone))
        assert git('rev-parse', 'HEAD', cwd=clone) == sha
        assert not git('status', '--porcelain', cwd=clone)
        git('fsck', '--full', cwd=clone)
        for row in refs:
            git('cat-file', '-e', row.split()[0], cwd=clone)
        assert git('ls-tree', '-r', 'HEAD', cwd=clone) == git('ls-tree', '-r', 'HEAD')
    receipt = {'passed': True, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_commit': sha, 'branch': branch, 'bundle': bundle.name,
        'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(), 'bytes': bundle.stat().st_size,
        'refs': refs, 'independent_clone_and_fsck_passed': True, 'worktree_tree_identical': True,
        'scope': 'Committed Git history only. Excludes ignored runtime files, credentials, database, registry images and raw output. Not an offline dependency installer or fresh-machine runtime acceptance.'}
    (folder / 'transfer.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': True, 'folder': str(folder), 'source_commit': sha,
                      'bytes': receipt['bytes'], 'sha256': receipt['bundle_sha256']}))


if __name__ == '__main__':
    main()
