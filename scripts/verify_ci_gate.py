"""Prove a real failed Jenkins unittest cannot publish desired environment state."""
import json
import subprocess
import time
from datetime import datetime, timezone

from scripts.gitops_trial import Jenkins, queued_build_number
from scripts.render_release import ROOT


def environment_head():
    return subprocess.check_output(['git', '--git-dir=/var/lib/release-lab/git/environment.git',
                                    'rev-parse', 'main'], text=True).strip()


def main():
    before = environment_head()
    client = Jenkins()
    queue = client.build('healthy', 'release-merged', fail_tests=True)
    deadline = time.monotonic() + 300
    number = None
    while time.monotonic() < deadline:
        item = client.json(queue + 'api/json')
        if item.get('cancelled'):
            raise RuntimeError('Negative trial cancelled')
        number = queued_build_number(item)
        if number:
            break
        time.sleep(2)
    if not number:
        raise TimeoutError('No negative-trial executor')
    while time.monotonic() < deadline:
        result = client.json(f'job/release-merged/{number}/api/json')
        if not result['building']:
            break
        time.sleep(2)
    else:
        raise TimeoutError('Negative trial did not finish')
    console = client.request(f'job/release-merged/{number}/consoleText')[0].decode()
    artifacts = {a['relativePath'] for a in result.get('artifacts', [])}
    after = environment_head()
    provenance = client.json(f'job/release-merged/{number}/artifact/output/source.json')
    passed = (result['result'] == 'FAILURE' and 'FAILED (failures=1)' in console
              and 'Intentional negative gate' in console and before == after
              and artifacts == {'output/source.json'})
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': passed,
              'job': 'release-merged', 'build': number, 'result': result['result'],
              'source': provenance, 'environment_before': before, 'environment_after': after,
              'artifacts': sorted(artifacts),
              'scope': 'Synthetic failing unittest in local acceptance job; not a failing application-source commit'}
    folder = ROOT / 'output' / f'negative-gate-{number}'
    folder.mkdir(exist_ok=True)
    (folder / 'console.txt').write_text(console)
    (ROOT / 'docs/evidence/ci-negative-gate.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not passed:
        raise AssertionError('Negative CI gate did not satisfy acceptance')


if __name__ == '__main__':
    main()
