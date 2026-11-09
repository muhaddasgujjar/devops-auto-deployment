"""Refresh the managed agent's scanner database before a constrained CI session."""
import json
import subprocess

from scripts.render_release import ROOT


def main():
    versions = json.loads((ROOT / 'versions.json').read_text())
    info = json.loads(subprocess.check_output(['docker', 'inspect', 'release-agent'], text=True))[0]
    if not info['State']['Running'] or info['Config'].get('Labels', {}).get('release-lab.managed') != 'true':
        raise SystemExit('Start only the existing managed agent after disabling legacy jobs')
    actual = subprocess.check_output(['docker', 'exec', 'release-agent', 'trivy', '--version'], text=True)
    if actual.splitlines()[0] != 'Version: ' + versions['trivy']:
        raise SystemExit('Agent scanner does not match versions.json')
    # Official upstream DB location. Do not use --skip-db-update or suppress findings.
    subprocess.run(['docker', 'exec', 'release-agent', 'trivy', 'image', '--download-db-only',
                    '--db-repository', 'ghcr.io/aquasecurity/trivy-db:2', '--timeout', '15m'],
                   check=True, timeout=930)
    print('Scanner database refresh completed; image scan remains a separate Jenkins gate')


if __name__ == '__main__':
    main()
