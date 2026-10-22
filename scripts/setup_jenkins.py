"""Build and start resource-limited local Jenkins with a separate trusted Docker agent."""
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from scripts.render_release import ROOT


def run(*args, timeout=120):
    result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=timeout)
    return result.stdout


def main():
    base = Path('/opt/release-lab')
    secret_dir = base / 'secrets'
    work = base / 'jenkins-build'
    work.mkdir(parents=True, exist_ok=True)
    if run('docker', 'ps', '-aq', '--filter', 'name=^release-jenkins$').strip():
        raise SystemExit('Jenkins container already exists; use its persisted state rather than replacing it')
    image = json.loads((ROOT / 'versions.json').read_text())['jenkins_image']
    url = json.loads((ROOT / 'output/gitops/local-git.json').read_text())['repository_url']
    controller = work / 'controller'
    (controller / 'ci').mkdir(parents=True, exist_ok=True)
    for name in ('plugins.txt', 'plugins.lock.txt', 'plugins.sha256', 'controller.Dockerfile', 'bootstrap.groovy'):
        shutil.copyfile(ROOT / 'ci' / name, controller / 'ci' / name)
    agent = work / 'agent'
    (agent / 'tools').mkdir(parents=True, exist_ok=True)
    for source, name in [('/usr/bin/docker', 'docker'), ('/usr/libexec/docker/cli-plugins/docker-buildx', 'docker-buildx'),
                         ('/usr/local/bin/trivy', 'trivy')]:
        shutil.copyfile(source, agent / 'tools' / name)
    shutil.copyfile(ROOT / 'ci/agent.Dockerfile', agent / 'Dockerfile')
    for tag, context, dockerfile in [('release-jenkins:local', controller, 'ci/controller.Dockerfile'),
                                      ('release-agent:local', agent, 'Dockerfile')]:
        log = ROOT / 'output' / (tag.split(':')[0] + '-build.log')
        print(f'Building {tag}; log: {log.name}', flush=True)
        with log.open('w') as stream:
            subprocess.run(['docker', 'build', '--build-arg', f'JENKINS_IMAGE={image}', '-f', str(context / dockerfile),
                            '-t', tag, str(context)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1200)
    source = base / 'source-snapshot'
    if source.exists():
        raise SystemExit('Source snapshot already exists; retain it for provenance and choose a new snapshot explicitly')
    source.mkdir()
    names = run('git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard').splitlines()
    for name in names:
        original = ROOT / name
        if original.is_file():
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    run('git', '-C', str(source), 'init', '--initial-branch=main')
    run('git', '-C', str(source), 'config', 'user.name', 'release-lab-snapshot')
    run('git', '-C', str(source), 'config', 'user.email', 'release-lab@localhost')
    run('git', '-C', str(source), 'add', '.')
    run('git', '-C', str(source), 'commit', '-m', 'Local trusted integration source snapshot')
    password = secret_dir / 'jenkins-password'
    if not password.exists():
        password.write_text(secrets.token_urlsafe(32))
    # Dedicated files only: the controller receives no read key, host key or kubeconfig.
    controller_secrets = base / 'jenkins-secrets'
    controller_secrets.mkdir(exist_ok=True)
    (controller_secrets / 'environment-url').write_text(url)
    (controller_secrets / 'environment-url').chmod(0o600)
    os.chown(controller_secrets / 'environment-url', 1000, 1000)
    for name in ('jenkins-password', 'environment-write'):
        shutil.copyfile(secret_dir / name, controller_secrets / name)
        (controller_secrets / name).chmod(0o600)
        os.chown(controller_secrets / name, 1000, 1000)
    os.chown(controller_secrets, 1000, 1000)
    controller_secrets.chmod(0o700)
    run('docker', 'run', '-d', '--name', 'release-jenkins', '--label', 'release-lab.managed=true',
        '--memory=768m', '--cpus=1', '--network', 'k3d-release-lab', '-p', '127.0.0.1:8082:8080',
        '-e', 'JAVA_OPTS=-Xms128m -Xmx384m -Djenkins.install.runSetupWizard=false',
        '-e', 'RELEASE_ENV_REPO_URL=' + url,
        '-v', 'release-jenkins-home:/var/jenkins_home', '-v', f'{controller_secrets}:/run/release-secrets',
        '-v', f'{source}:/opt/release-source:ro', 'release-jenkins:local')
    deadline = time.monotonic() + 240
    while not (controller_secrets / 'agent-secret').exists():
        if time.monotonic() >= deadline:
            raise SystemExit('Jenkins bootstrap not ready; inspect docker logs release-jenkins')
        time.sleep(3)
    remoting = run('docker', 'exec', 'release-jenkins', 'find', '/var/jenkins_home/war/WEB-INF/lib', '-name', 'remoting-*.jar').strip()
    if not remoting or '\n' in remoting:
        raise SystemExit('Cannot resolve the installed Jenkins remoting jar')
    run('docker', 'cp', 'release-jenkins:' + remoting, str(work / 'agent.jar'))
    agent_env = secret_dir / 'agent.env'
    agent_env.write_text('JENKINS_AGENT_SECRET=' + (controller_secrets / 'agent-secret').read_text().strip() + '\nENV_REPO_URL=' + url + '\nTRIVY_DB_REPOSITORY=ghcr.io/aquasecurity/trivy-db:2\n')
    agent_env.chmod(0o600)
    # Host networking permits the loopback lab registry. Docker access is trusted/root-equivalent.
    run('docker', 'run', '-d', '--name', 'release-agent', '--label', 'release-lab.managed=true',
        '--network', 'host', '--memory=512m', '--cpus=2', '--group-add', str(Path('/var/run/docker.sock').stat().st_gid),
        '--env-file', str(agent_env), '-v', '/var/run/docker.sock:/var/run/docker.sock',
        '-v', f'{source}:/opt/release-source:ro', '-v', f'{secret_dir}/known_hosts:/etc/release-known-hosts:ro',
        '-v', f'{work}/agent.jar:/opt/agent.jar:ro', '--entrypoint', '/bin/sh', 'release-agent:local', '-c',
        'exec java -Xmx192m -jar /opt/agent.jar -url http://127.0.0.1:8082/ -secret "$JENKINS_AGENT_SECRET" -name release-linux -webSocket -workDir /home/jenkins/agent')
    print('Jenkins: http://localhost:8082 ; admin password remains in /opt/release-lab/secrets/jenkins-password', flush=True)


if __name__ == '__main__':
    main()
