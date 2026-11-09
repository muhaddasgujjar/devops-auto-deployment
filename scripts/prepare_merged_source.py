"""Prepare a clean committed snapshot, preserving every older source snapshot."""
import argparse
import json
import subprocess
from pathlib import Path

from scripts.render_release import ROOT


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy-to-agent', action='store_true')
    args = parser.parse_args()
    if run('git', '-C', str(ROOT), 'status', '--porcelain'):
        raise SystemExit('Commit the reviewed source before preparing an acceptance snapshot')
    sha = run('git', '-C', str(ROOT), 'rev-parse', 'HEAD')
    source = Path('/opt/release-lab/source-revisions') / sha
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        run('git', 'clone', '--no-hardlinks', '--no-checkout', str(ROOT), str(source))
        run('git', '-C', str(source), 'checkout', '--detach', sha)
    if run('git', '-C', str(source), 'rev-parse', 'HEAD') != sha or run('git', '-C', str(source), 'status', '--porcelain'):
        raise RuntimeError('Existing snapshot has unexpected content; refusing replacement')
    destination = '/opt/release-merged-source/' + sha
    if args.copy_to_agent:
        info = json.loads(run('docker', 'inspect', 'release-agent'))[0]
        if info['Config'].get('Labels', {}).get('release-lab.managed') != 'true' or not info['State']['Running']:
            raise RuntimeError('Only the running, managed lab agent is supported')
        exists = subprocess.run(['docker', 'exec', 'release-agent', 'test', '-d', destination], capture_output=True)
        if exists.returncode:
            run('docker', 'exec', '--user', '0', 'release-agent', 'mkdir', '-p', destination)
            run('docker', 'cp', str(source) + '/.', 'release-agent:' + destination)
            run('docker', 'exec', '--user', '0', 'release-agent', 'chown', '-R', '1000:1000', destination)
        if run('docker', 'exec', 'release-agent', 'git', '-C', destination, 'rev-parse', 'HEAD') != sha:
            raise RuntimeError('Agent source does not match the selected commit')
        if run('docker', 'exec', 'release-agent', 'git', '-C', destination, 'status', '--porcelain'):
            raise RuntimeError('Agent snapshot contains uncommitted changes')
    print(json.dumps({'source_commit': sha, 'host_snapshot': str(source),
                      'agent_snapshot': destination, 'copied_to_agent': args.copy_to_agent}))


if __name__ == '__main__':
    main()
