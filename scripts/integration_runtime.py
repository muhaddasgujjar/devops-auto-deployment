"""Restore local Git transport and optionally manage labelled CI containers."""
import argparse
import json
import subprocess
from pathlib import Path

from scripts.render_release import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--profile', choices=['lean', 'full'], default='full',
                        help='Lean starts configured Git transport without starting CI containers')
    args = parser.parse_args()
    names = ('release-jenkins', 'release-agent') if args.action != 'stop' else ('release-agent', 'release-jenkins')
    if args.action == 'start' and args.profile == 'lean':
        names = ()
    if args.action == 'start' and Path('/opt/release-lab/secrets/sshd_config').exists():
        subprocess.run(['bash', str(ROOT / 'scripts/setup-local-git.sh')], check=True)
    report = {}
    for name in names:
        result = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True)
        if result.returncode:
            continue
        obj = json.loads(result.stdout)[0]
        if obj['Config'].get('Labels', {}).get('release-lab.managed') != 'true':
            raise SystemExit(f'Refusing to manage unlabelled container {name}')
        running = obj['State']['Running']
        if args.action == 'start' and not running:
            subprocess.run(['docker', 'start', name], check=True)
        elif args.action == 'stop' and running:
            subprocess.run(['docker', 'stop', '--time', '30', name], check=True)
        report[name] = {'was_running': running, 'action': args.action}
    print(json.dumps(report))


if __name__ == '__main__':
    main()
