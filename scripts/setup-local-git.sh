#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 ]] || { echo 'Run as root inside the dedicated lab'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
new_server=false
dpkg-query -W -f='${Status}' openssh-server 2>/dev/null | grep -q 'install ok installed' || new_server=true
if $new_server; then
apt-get update -qq
policy=/usr/sbin/policy-rc.d
created_policy=false
if [[ ! -e "$policy" ]]; then
  printf '#!/bin/sh\nexit 101\n' > "$policy"
  chmod 755 "$policy"
  created_policy=true
  trap 'if $created_policy; then rm -f /usr/sbin/policy-rc.d; fi' EXIT
fi
apt-get install -y --no-install-recommends openssh-server git
if $created_policy; then rm -f "$policy"; created_policy=false; fi
systemctl disable --now ssh.socket ssh.service
fi
home=/var/lib/release-lab/git
secrets=/opt/release-lab/secrets
install -d -m 700 "$secrets"
install -d -m 755 "$home" /run/sshd
id release-git >/dev/null 2>&1 || useradd --system --home-dir "$home" --shell /bin/sh release-git
# A random, discarded password hash unlocks public-key login; password auth is off.
if passwd -S release-git | grep -q ' L '; then
  python3 -c 'import crypt,secrets; print(crypt.crypt(secrets.token_hex(32),crypt.mksalt(crypt.METHOD_SHA512)))' | usermod --password "$(cat)" release-git
fi
if [[ ! -d "$home/environment.git" ]]; then
  git init --bare --initial-branch=main "$home/environment.git"
fi
for role in read write; do
  [[ -f "$secrets/environment-$role" ]] || ssh-keygen -q -t ed25519 -N '' -C "release-lab-$role" -f "$secrets/environment-$role"
done
[[ -f "$secrets/git-host-key" ]] || ssh-keygen -q -t ed25519 -N '' -C release-lab-git-host -f "$secrets/git-host-key"
install -m 755 scripts/git_ssh_command.py "$home/git_ssh_command.py"
{
  for role in read write; do
    printf 'restrict,command="/usr/bin/python3 %s/git_ssh_command.py %s" %s\n' "$home" "$role" "$(cat "$secrets/environment-$role.pub")"
  done
} > "$home/authorized_keys"
chown -R release-git:release-git "$home"
chmod 600 "$home/authorized_keys"
git -c safe.directory="$home/environment.git" --git-dir="$home/environment.git" config receive.denyNonFastForwards true
git -c safe.directory="$home/environment.git" --git-dir="$home/environment.git" config receive.denyDeletes true
gateway=$(docker network inspect k3d-release-lab --format '{{(index .IPAM.Config 0).Gateway}}')
cat > "$secrets/sshd_config" <<EOF
Port 2222
ListenAddress 127.0.0.1
ListenAddress $gateway
HostKey $secrets/git-host-key
PidFile $secrets/sshd.pid
AuthorizedKeysFile $home/authorized_keys
AllowUsers release-git
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
DisableForwarding yes
PermitTTY no
UsePAM no
StrictModes yes
EOF
sshd -t -f "$secrets/sshd_config"
git_running=false
if [[ -f "$secrets/sshd.pid" ]]; then
  git_pid=$(cat "$secrets/sshd.pid")
  if [[ $git_pid =~ ^[0-9]+$ && -r /proc/$git_pid/cmdline ]]; then
    git_command=$(tr '\0' ' ' < "/proc/$git_pid/cmdline")
    [[ $git_command == *"sshd -f $secrets/sshd_config"* ]] && git_running=true
  fi
fi
if ! $git_running; then
  /usr/sbin/sshd -f "$secrets/sshd_config" -E "$secrets/sshd.log"
fi
hostkey=$(cut -d' ' -f1,2 "$secrets/git-host-key.pub")
printf '[%s]:2222 %s\n[127.0.0.1]:2222 %s\n' "$gateway" "$hostkey" "$hostkey" > "$secrets/known_hosts"
chmod 644 "$secrets/known_hosts"
mkdir -p output/gitops
printf '{"repository_url":"ssh://release-git@%s:2222%s"}\n' "$gateway" "$home/environment.git" > output/gitops/local-git.json
echo 'Local environment Git transport ready; private keys remain outside the workspace.'
