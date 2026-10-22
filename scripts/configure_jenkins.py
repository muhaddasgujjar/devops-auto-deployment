"""Apply the reviewed local Jenkins bootstrap through its authenticated admin API."""
import json
import argparse
import os
from pathlib import Path
from urllib.parse import urlencode

from scripts.gitops_trial import Jenkins
from scripts.render_release import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-main', action='store_true')
    args = parser.parse_args()
    folder = Path('/opt/release-lab/jenkins-secrets')
    url = json.loads((ROOT / 'output/gitops/local-git.json').read_text())['repository_url']
    target = folder / 'environment-url'
    target.write_text(url)
    target.chmod(0o600)
    os.chown(target, 1000, 1000)
    client = Jenkins()
    crumb = client.json('crumbIssuer/api/json')
    script = (ROOT / 'ci/bootstrap.groovy').read_text()
    if args.enable_main:
        script = script.replace('return null', "Jenkins.get().getItem('release-main').setDisabled(false)\nreturn null")
    content, _ = client.request('scriptText', urlencode({'script': script}).encode(),
                               {crumb['crumbRequestField']: crumb['crumb'], 'Content-Type': 'application/x-www-form-urlencoded'})
    if content.strip():
        (ROOT / 'output/jenkins-config-error.txt').write_bytes(content)
        raise SystemExit(content.decode()[:3000])
    print('Jenkins local and main-branch jobs configured')


if __name__ == '__main__':
    main()
