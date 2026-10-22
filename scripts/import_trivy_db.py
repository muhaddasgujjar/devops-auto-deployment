"""Import a digest-verified, unexpired official database into the idle local agent."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.render_release import ROOT

IMPORT = '''
import hashlib,json,os,tarfile
from pathlib import Path
from datetime import datetime,timezone
archive=Path('/tmp/release-db.tar.gz')
expected=__DIGEST__
if hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()!=expected:
 raise SystemExit('Database archive checksum mismatch inside agent')
target=Path('/var/jenkins_home/.cache/trivy/db')
target.mkdir(parents=True,exist_ok=True)
with tarfile.open(archive) as tar:
 members=tar.getmembers()
 if {m.name for m in members}!={'trivy.db','metadata.json'} or any(not m.isfile() or m.size>5*1024**3 for m in members):
  raise SystemExit('Unexpected database archive members')
 metadata=json.load(tar.extractfile('metadata.json'))
 if metadata.get('Version')!=2 or datetime.fromisoformat(metadata['NextUpdate'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
  raise SystemExit('Refusing an expired/incompatible vulnerability database')
 tar.extractall(target,filter='data')
metadata['DownloadedAt']=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
(target/'metadata.json').write_text(json.dumps(metadata))
for path in [target.parent,target,*target.iterdir()]:
 os.chown(path,1000,1000)
print(json.dumps(metadata))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    archive = parser.parse_args().archive
    evidence = json.loads(archive.with_suffix('.json').read_text())
    expected = evidence['layer_digest'].removeprefix('sha256:')
    if hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != expected:
        raise SystemExit('Archive does not match its OCI layer digest')
    obj = json.loads(subprocess.check_output(['docker', 'inspect', 'release-agent']))[0]
    if obj['Config'].get('Labels', {}).get('release-lab.managed') != 'true':
        raise SystemExit('Only the managed lab agent is supported')
    from scripts.gitops_trial import Jenkins
    client = Jenkins()
    for job in ('release-local', 'release-main'):
        build = client.json(f'job/{job}/api/json').get('lastBuild')
        if build and client.json(f'job/{job}/{build["number"]}/api/json')['building']:
            raise SystemExit('Wait for all builds before importing the database')
    subprocess.run(['docker', 'cp', str(archive), 'release-agent:/tmp/release-db.tar.gz'], check=True, capture_output=True)
    result = subprocess.run(['docker', 'exec', '-i', '--user', 'root', 'release-agent', 'python3', '-'],
                            input=IMPORT.replace('__DIGEST__', repr(expected)), text=True, capture_output=True, check=True)
    evidence['database'] = json.loads(result.stdout)
    (ROOT / 'output/gitops/trivy-db-import.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
