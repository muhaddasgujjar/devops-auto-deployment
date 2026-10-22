"""Forced SSH command: restrict each key to one bare environment repository."""
import os
import shlex
import sys

REPOSITORY = '/var/lib/release-lab/git/environment.git'


def allowed_command(original, role):
    if role not in ('read', 'write'):
        raise ValueError('Unknown repository role')
    args = shlex.split(original)
    verbs = {'git-upload-pack'} if role == 'read' else {'git-upload-pack', 'git-receive-pack'}
    if len(args) != 2 or args[0] not in verbs or args[1] != REPOSITORY:
        raise ValueError('Only the designated environment repository is permitted')
    return [args[0], REPOSITORY]


if __name__ == '__main__':
    try:
        command = allowed_command(os.environ.get('SSH_ORIGINAL_COMMAND', ''), sys.argv[1])
    except (ValueError, IndexError):
        raise SystemExit('Repository access denied')
    os.execvp(command[0], command)
