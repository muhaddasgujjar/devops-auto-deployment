"""Commit digest-only desired state to environment Git; never calls Kubernetes."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from scripts.render_release import IMAGE, COMMIT, render


def git(directory, *args, check=True):
    result = subprocess.run(['git', '-C', str(directory), *args],
                            capture_output=True, text=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError('Git operation failed: ' + result.stderr[-2000:])
    return result


def publish(repository, image, commit, release_id, evidence):
    # Validate before cloning or creating a commit. Environment paths are fixed.
    if not IMAGE.fullmatch(image) or not COMMIT.fullmatch(commit):
        raise ValueError('A digest reference and full source SHA are required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', release_id):
        raise ValueError('Invalid release identifier')
    if not repository.startswith(('ssh://', 'https://')) and not Path(repository).is_absolute():
        raise ValueError('Use an explicit SSH/HTTPS URL or an absolute local test repository')
    if repository.startswith(('ssh://', 'https://')):
        parsed = urlsplit(repository)
        if parsed.password is not None or (parsed.scheme == 'https' and parsed.username is not None):
            raise ValueError('Pass credentials through a credential provider, not a repository URL')
    with tempfile.TemporaryDirectory(prefix='release-env-') as directory:
        git(directory, 'clone', '--branch', 'main', '--single-branch', '--', repository, directory)
        target = Path(directory) / 'environments/dev'
        render(image, commit, target)
        rollout = target / 'rollout.yaml'
        rollout.write_text(rollout.read_text().replace(f'value: "{commit}"', f'value: "{commit}-{release_id}"'), newline='\n')
        git(directory, 'config', 'user.name', 'release-ci')
        git(directory, 'config', 'user.email', 'release-ci@localhost')
        git(directory, 'add', '--', 'environments/dev')
        changed = git(directory, 'diff', '--cached', '--quiet', check=False)
        if changed.returncode not in (0, 1):
            raise RuntimeError('Unable to inspect staged release')
        if changed.returncode:
            git(directory, 'commit', '-m', f'Release {commit} ({release_id})')
            # No force/rebase: a conflicting writer must fail and be investigated.
            git(directory, 'push', 'origin', 'HEAD:main')
        result = {'source_commit': commit, 'image': image, 'release_id': release_id,
                  'environment_commit': git(directory, 'rev-parse', 'HEAD').stdout.strip(),
                  'changed': bool(changed.returncode)}
        evidence = Path(evidence)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(result, indent=2))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.repository, args.image, args.commit, args.release_id, args.evidence)))


if __name__ == '__main__':
    main()
