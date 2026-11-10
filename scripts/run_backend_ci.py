"""Trigger one authenticated backend job and retain its actual artifacts and result."""
import argparse
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from scripts.gitops_trial import Jenkins, queued_build_number
from scripts.render_release import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--negative-test', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'output' / ('backend-ci-trial-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True, exist_ok=False)
    client = Jenkins()
    client.wait_ready()
    crumb = client.json('crumbIssuer/api/json')
    _, headers = client.request('job/backend-gate/buildWithParameters',
        urlencode({'FAIL_TEST_GATE': 'true' if args.negative_test else 'false'}).encode(),
        {crumb['crumbRequestField']: crumb['crumb'], 'Content-Type': 'application/x-www-form-urlencoded'})
    queue, number = headers['Location'], None
    deadline = time.monotonic() + 1300
    while time.monotonic() < deadline:
        queued = client.json(queue + 'api/json')
        if queued.get('cancelled'):
            raise RuntimeError('Backend queue item cancelled')
        number = queued_build_number(queued)
        if number:
            break
        time.sleep(2)
    if number is None:
        raise TimeoutError('Backend job never started')
    print('Backend Jenkins build ' + str(number), flush=True)
    while time.monotonic() < deadline:
        result = client.json(f'job/backend-gate/{number}/api/json')
        if not result['building']:
            (folder / 'jenkins-build.json').write_text(json.dumps(result, indent=2))
            (folder / 'console.txt').write_bytes(client.request(f'job/backend-gate/{number}/consoleText')[0])
            for artifact in result.get('artifacts', []):
                name = artifact['fileName']
                if name.endswith('.json') and '/' not in name:
                    (folder / name).write_bytes(client.request(f'job/backend-gate/{number}/artifact/' + artifact['relativePath'])[0])
            outcome = json.loads((folder / 'result.json').read_text())
            tests = json.loads((folder / 'tests.json').read_text())
            expected = 'FAILURE' if args.negative_test else 'SUCCESS'
            if result['result'] != expected or not outcome['ephemeral_resources_removed']:
                raise AssertionError('Backend CI outcome failed acceptance; retained ' + str(folder))
            if args.negative_test:
                if tests['passed'] or tests['failures'] != 1 or outcome['published']:
                    raise AssertionError('Negative gate did not block publication')
            elif not outcome['passed'] or not outcome['published']:
                raise AssertionError('Backend CI did not publish its verified runtime image')
            print(json.dumps({'accepted': True, 'negative': args.negative_test, 'build': number,
                              'result': result['result'], 'raw_trial': folder.relative_to(ROOT).as_posix()}), flush=True)
            return
        time.sleep(3)
    raise TimeoutError('Backend job exceeded the observation window')


if __name__ == '__main__':
    main()
