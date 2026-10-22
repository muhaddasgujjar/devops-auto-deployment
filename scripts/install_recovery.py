"""Install the bounded local recovery observer under systemd."""
import subprocess
from pathlib import Path
from scripts.render_release import ROOT


def main():
    unit = Path('/etc/systemd/system/release-lab-recovery.service')
    unit.write_text('[Unit]\nDescription=Release lab GitOps recovery observer\nAfter=docker.service\n'
                    '[Service]\nType=simple\nWorkingDirectory=' + str(ROOT).replace('%', '%%') + '\n'
                    'ExecStart=/opt/release-lab/venv/bin/python -u -m scripts.recovery --watch\n'
                    'Restart=on-failure\nRestartSec=5\nMemoryMax=192M\nCPUQuota=25%\nUMask=0077\n'
                    'TimeoutStopSec=30\n[Install]\nWantedBy=multi-user.target\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', unit.name], check=True)
    subprocess.run(['systemctl', 'restart', unit.name], check=True)
    print('Installed local recovery observer; Git writes use the restricted environment key')


if __name__ == '__main__':
    main()
