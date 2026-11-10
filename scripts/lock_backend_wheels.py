"""Record the exact Linux/musl wheel hashes used by the pinned backend build."""
import hashlib
import json
from pathlib import Path

from scripts.render_release import ROOT


def main():
    wheels = ROOT / 'output/backend-musl-wheels'
    indexed = {path.name.split('-')[0].lower().replace('_', '-'): path for path in wheels.glob('*.whl')}
    locked, manifest = [], {}
    for line in (ROOT / 'requirements-backend-lock.txt').read_text().splitlines():
        if not line.strip():
            continue
        name, version = line.split('==')
        path = indexed[name.lower().replace('_', '-')]
        if path.name.split('-')[1] != version:
            raise ValueError('Wheel version mismatch')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        locked.append(line + ' --hash=sha256:' + digest)
        manifest[path.name] = digest
    (ROOT / 'requirements-backend-musl.lock').write_text('\n'.join(locked) + '\n')
    (ROOT / 'backend-wheel-lock.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'wheels_locked': len(manifest), 'target': 'CPython 3.12 Linux musl x86_64'}))


if __name__ == '__main__':
    main()
