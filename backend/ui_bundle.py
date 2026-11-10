"""Validate the compiled portal against its exact source inputs before packaging."""
import hashlib
import json
import shutil
from pathlib import Path


def inputs(frontend):
    names = ['package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts']
    for directory in ('src', 'scripts', 'tests'):
        names.extend(path.relative_to(frontend).as_posix() for path in (frontend / directory).rglob('*') if path.is_file())
    return sorted(names)


def source_hash(frontend):
    digest = hashlib.sha256()
    for name in inputs(frontend):
        digest.update(name.encode() + b'\0')
        digest.update((frontend / name).read_bytes())
    return digest.hexdigest()


def verify(frontend, directory=None):
    directory = directory or frontend / 'dist'
    manifest = json.loads((directory / 'build.json').read_text())
    if manifest.get('format') != 1 or manifest['input_sha256'] != source_hash(frontend):
        raise ValueError('Rebuild the portal: production assets do not match the current source')
    for name, expected in manifest['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Portal asset hash or path is invalid')
    if 'index.html' not in manifest['files']:
        raise ValueError('Portal entry document is missing')
    return manifest


def copy_bundle(frontend, destination):
    manifest = verify(frontend)
    if destination.exists():
        if verify(frontend, destination) != manifest:
            raise ValueError('Refusing to overwrite an existing portal snapshot')
        return
    destination.mkdir(parents=True)
    for name in [*manifest['files'], 'build.json']:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frontend / 'dist' / name, target)
