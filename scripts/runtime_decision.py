"""Interpret only the intended candidate, preserving stable service on faults."""


def decision(scenario, expected_revision, environment_commit, previous_hash,
             rollout, application, analyses, stable_hash):
    spec, state = rollout.get('spec', {}), rollout.get('status', {})
    env = spec.get('template', {}).get('spec', {}).get('containers', [{}])[0].get('env', [])
    revision = next((e.get('value') for e in env if e.get('name') == 'APP_REVISION'), None)
    candidate = state.get('currentPodHash')
    sync = application.get('status', {}).get('sync', {})
    generation = rollout.get('metadata', {}).get('generation')
    observed = generation is not None and state.get('observedGeneration') is not None and str(state['observedGeneration']) == str(generation)
    if not (previous_hash and observed and revision == expected_revision and candidate and candidate != previous_hash
            and sync.get('revision') == environment_commit and sync.get('status') == 'Synced'):
        return None
    phases = {a.get('status', {}).get('phase') for a in analyses
              if a.get('metadata', {}).get('labels', {}).get('rollouts-pod-template-hash') == candidate}
    if scenario != 'healthy' and stable_hash != previous_hash:
        raise AssertionError('Fault candidate changed the stable service selector')
    if scenario == 'healthy' and 'Successful' in phases and stable_hash == candidate:
        return 'candidate-promoted-through-gitops'
    if scenario in ('error', 'latency') and 'Failed' in phases and state.get('abort'):
        return 'candidate-rejected-through-gitops'
    if scenario == 'startup' and state.get('abort'):
        return 'readiness-aborted-through-gitops'
    if scenario == 'no-traffic' and 'Inconclusive' in phases:
        return 'missing-traffic-inconclusive-through-gitops'
    if scenario == 'telemetry-outage' and phases.intersection({'Error', 'Inconclusive'}):
        return 'missing-telemetry-blocked-through-gitops'
    return None
