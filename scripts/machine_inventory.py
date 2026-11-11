"""Read-only target inventory; never reads credentials or starts services."""
import argparse
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def probe(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'available': result.returncode == 0, 'version': result.stdout.strip()[:500] if result.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False, 'version': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output/machine-inventory.json'))
    args = parser.parse_args()
    memory = None
    if Path('/proc/meminfo').exists():
        memory = int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemTotal:'))) * 1024
    elif platform.system() == 'Windows':
        value = probe(['powershell.exe', '-NoProfile', '-Command', '(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory'])
        if value['available']: memory = int(value['version'])
    disk = shutil.disk_usage(Path.cwd())
    tools = {name: probe(command) for name, command in {
        'git': ['git', '--version'], 'docker': ['docker', '--version'],
        'docker_daemon': ['docker', 'info', '--format', '{{.OSType}}/{{.Architecture}}'],
        'kubectl': ['kubectl', 'version', '--client=true', '-o', 'json'],
        'k3d': ['k3d', 'version'], 'trivy': ['trivy', '--version'],
        'node': ['node', '--version'], 'npm': ['npm.cmd' if os.name == 'nt' else 'npm', '--version']}.items()}
    result = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'os': platform.system(),
        'architecture': platform.machine(), 'python': platform.python_version(), 'logical_cpus': os.cpu_count(),
        'visible_ram_bytes': memory, 'checkout_disk_free_bytes': disk.free, 'tools': tools,
        'assessment': 'Inventory only. Compare pins and check Linux systemd, ports, clock, RAM/disk headroom and network before installation. GPU VRAM is not host RAM.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'inventory': str(args.output), 'os': result['os'], 'logical_cpus': result['logical_cpus'], 'visible_ram_bytes': memory}))


if __name__ == '__main__':
    main()
