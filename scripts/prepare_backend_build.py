"""Whitelist source and verified wheels into a credential-free Docker build context."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from scripts.render_release import ROOT


def prepare(context, wheels):
    context.mkdir(parents=True, exist_ok=False)
    for source in (ROOT / 'backend').rglob('*'):
        if source.is_file() and source.suffix in {'.py', '.mako'}:
            target = context / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for directory in ('backend_tests',):
        for source in (ROOT / directory).glob('*.py'):
            target = context / directory / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    files = ['alembic.ini', 'requirements-backend-musl.lock', 'ci/backend.Dockerfile',
             'ci/backend_tests_entrypoint.py', 'scripts/validate_backend.py', 'scripts/render_release.py',
             'docs/evidence/ci-gitops-acceptance.json', 'docs/evidence/runtime-failure-validation.json',
             'docs/evidence/ci-negative-gate.json']
    for name in files:
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    manifest = json.loads((ROOT / 'backend-wheel-lock.json').read_text())
    wheelhouse = context / 'wheelhouse'
    wheelhouse.mkdir()
    for name, digest in manifest.items():
        source = wheels / name
        if source.name != name or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Backend wheel hash mismatch')
        shutil.copyfile(source, wheelhouse / name)
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--wheels', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.context, args.wheels)
    print('Prepared whitelisted backend source and verified wheelhouse')


if __name__ == '__main__':
    main()
