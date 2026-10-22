"""Durable environment-Git release lease shared by publishers and recovery."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

CONTROL = 'release-control.json'


def now():
    return datetime.now(timezone.utc)


def deadline(seconds):
    return (now() + timedelta(seconds=seconds)).isoformat()


def read_control(directory):
    path = Path(directory) / CONTROL
    return json.loads(path.read_text()) if path.exists() else None


def write_control(directory, state):
    (Path(directory) / CONTROL).write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', newline='\n')


def decide(state, observation, current_time=None):
    """Pure, bounded state decisions; never equate traffic rollback with recovery."""
    phase = state['phase']
    expired = (current_time or now()) >= datetime.fromisoformat(state['deadline'])
    if phase == 'deploying':
        if observation.get('matches') and observation.get('abort'):
            return 'restore'
        if (observation.get('matches') and observation.get('healthy')
                and observation.get('pre') == observation.get('post') == 'Successful'):
            return 'complete'
        return 'restore' if expired else 'wait'
    if phase == 'recovering':
        if observation.get('healthy') and observation.get('matches') and observation.get('verified_samples', 0) >= 3:
            return 'complete'
        return 'fail' if expired else 'wait'
    return 'idle'
