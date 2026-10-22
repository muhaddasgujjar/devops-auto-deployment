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


def validate_rollout_policy(spec):
    blue_green = spec.get('strategy', {}).get('blueGreen', {})
    if blue_green.get('scaleDownDelayRevisionLimit', 0) > spec.get('revisionHistoryLimit', 10):
        raise ValueError('Scale-down revision limit cannot exceed revision history limit')
    if ('postPromotionAnalysis' in blue_green and 'scaleDownDelaySeconds' in blue_green
            and blue_green['scaleDownDelaySeconds'] < 150):
        raise ValueError('Retention must cover the 120-second post gate plus recovery margin')


def decide(state, observation, current_time=None):
    """Pure, bounded state decisions; never equate traffic rollback with recovery."""
    phase = state['phase']
    expired = (current_time or now()) >= datetime.fromisoformat(state['deadline'])
    if phase == 'deploying':
        if observation.get('matches') and (observation.get('abort') or observation.get('invalid_spec')):
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
