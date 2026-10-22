"""Download the current official GHCR database layer with OCI digest verification."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


def stage_in_wsl(archive):
    """Stream from Windows to Linux, avoiding large reads through the WSL mount."""
    if os.name != 'nt':
        raise ValueError('WSL staging is a Windows-only option')
    archive = Path(archive)
    metadata = json.loads(archive.with_suffix('.json').read_text())
    if 'sha256:' + hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != metadata['layer_digest']:
        raise ValueError('Refusing to stage a database with a mismatched checksum')
    destination = '/opt/release-lab/cache/trivy-db-current.tar.gz'
    code = '''import hashlib,json,pathlib,shutil,sys
p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
part=p.with_suffix('.part')
with part.open('wb') as target: shutil.copyfileobj(sys.stdin.buffer,target,65536)
metadata=json.loads(sys.argv[2])
with part.open('rb') as source: actual='sha256:'+hashlib.file_digest(source,'sha256').hexdigest()
if actual!=metadata['layer_digest']: raise SystemExit('WSL transfer checksum mismatch')
part.replace(p); p.with_suffix('.json').write_text(json.dumps(metadata))
'''
    process = subprocess.Popen(['wsl', '--distribution', 'Ubuntu-24.04', '--user', 'root', '--exec',
                                'python3', '-c', code, destination, json.dumps(metadata)], stdin=subprocess.PIPE)
    try:
        with archive.open('rb') as source:
            shutil.copyfileobj(source, process.stdin, 65536)
        process.stdin.close()
        if process.wait(timeout=120):
            raise RuntimeError('WSL database staging failed')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return destination


def fetch(archive):
    token = json.load(urlopen('https://ghcr.io/token?scope=repository:aquasecurity/trivy-db:pull&service=ghcr.io', timeout=30))['token']
    headers = {'Authorization': 'Bearer ' + token}
    request = Request('https://ghcr.io/v2/aquasecurity/trivy-db/manifests/2',
                      headers={**headers, 'Accept': 'application/vnd.oci.image.manifest.v1+json'})
    manifest = json.load(urlopen(request, timeout=30))
    layer, = manifest['layers']
    if layer['mediaType'] != 'application/vnd.aquasec.trivy.db.layer.v1.tar+gzip':
        raise ValueError('Unexpected vendor database layer type')
    digest = layer['digest']
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise ValueError('Unexpected OCI digest')
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    part = archive.with_suffix('.part')
    hasher = hashlib.sha256()
    total = 0
    request = Request('https://ghcr.io/v2/aquasecurity/trivy-db/blobs/' + digest, headers=headers)
    with urlopen(request, timeout=60) as response, part.open('wb') as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
            hasher.update(chunk)
            total += len(chunk)
            if total % (16 * 1024 * 1024) == 0:
                print(f'Downloaded {total // (1024 * 1024)} MiB of official database', flush=True)
    if total != layer['size'] or 'sha256:' + hasher.hexdigest() != digest:
        raise ValueError('Vendor database layer size/checksum mismatch')
    part.replace(archive)
    evidence = {'repository': 'ghcr.io/aquasecurity/trivy-db:2', 'layer_digest': digest, 'size': total}
    archive.with_suffix('.json').write_text(json.dumps(evidence, indent=2))
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--stage-in-wsl', action='store_true', help='Stream verified data to the Linux filesystem on low-memory Windows hosts')
    args = parser.parse_args()
    result = fetch(args.archive)
    if args.stage_in_wsl:
        result['linux_archive'] = stage_in_wsl(args.archive)
    print(json.dumps(result))
