"""Download the current official GHCR database layer with OCI digest verification."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


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
    print(json.dumps(fetch(parser.parse_args().archive)))
