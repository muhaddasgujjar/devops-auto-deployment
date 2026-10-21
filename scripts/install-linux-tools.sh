#!/usr/bin/env bash
# Run with sudo in a dedicated Ubuntu 24.04 lab/WSL distribution.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo on the dedicated lab host.' >&2; exit 1; }
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || { echo 'This installer supports Ubuntu 24.04 only.' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'This installer supports amd64 only.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-venv
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location --retry 3 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
# Apt verifies package signatures. Pin versions and retain the installed inventory.
docker_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["docker_engine_apt"])')
containerd_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["containerd_apt"])')
buildx_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["docker_buildx_apt"])')
apt-get install -y --no-install-recommends "docker-ce=$docker_version" "docker-ce-cli=$docker_version" "containerd.io=$containerd_version" "docker-buildx-plugin=$buildx_version"
mkdir -p output/install
dpkg-query -W docker-ce docker-ce-cli containerd.io docker-buildx-plugin > output/install/docker-packages.txt

k3d_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["k3d"])')
trivy_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["trivy"])')
kube_version=$(python3 -c 'import json; print(json.load(open("versions.json"))["k3s_image"].split(":")[1].split("-k3s")[0])')
download() { curl --fail --silent --show-error --location --retry 3 "$1" -o "$2"; }
(
  cd output/install
  download "https://github.com/k3d-io/k3d/releases/download/$k3d_version/k3d-linux-amd64" k3d-linux-amd64
  download "https://github.com/k3d-io/k3d/releases/download/$k3d_version/checksums.txt" k3d-checksums.txt
  awk '$2 ~ /(^|\/)k3d-linux-amd64$/ {print $1 "  k3d-linux-amd64"}' k3d-checksums.txt | sha256sum --check -
  install -m 0755 k3d-linux-amd64 /usr/local/bin/k3d
  download "https://dl.k8s.io/release/$kube_version/bin/linux/amd64/kubectl" kubectl
  download "https://dl.k8s.io/release/$kube_version/bin/linux/amd64/kubectl.sha256" kubectl.sha256
  printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum --check -
  install -m 0755 kubectl /usr/local/bin/kubectl
  archive="trivy_${trivy_version}_Linux-64bit.tar.gz"
  download "https://github.com/aquasecurity/trivy/releases/download/v$trivy_version/$archive" "$archive"
  download "https://github.com/aquasecurity/trivy/releases/download/v$trivy_version/trivy_${trivy_version}_checksums.txt" trivy-checksums.txt
  grep -F " $archive" trivy-checksums.txt | sha256sum --check -
  tar -xzf "$archive" trivy
  install -m 0755 trivy /usr/local/bin/trivy
)
if [[ $(ps -p 1 -o comm=) == systemd ]]; then
  systemctl start docker
else
  service docker start
fi
docker info >/dev/null
k3d version
kubectl version --client
trivy --version
python3 -m venv /opt/release-lab/venv
/opt/release-lab/venv/bin/python -m pip install --disable-pip-version-check -r requirements-validation.txt
/opt/release-lab/venv/bin/python -m pip check
bash scripts/install-review-tools.sh
echo 'Tools ready. Use sudo for Docker on this dedicated host; no user group memberships were changed.'
