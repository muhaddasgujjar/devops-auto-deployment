"""Normalize curated portable reports; document instructions are never executed."""
from backend.contracts import FailedBuild, ReleaseObservation

VERDICTS = {
    'candidate-promoted-through-gitops': 'promoted',
    'candidate-rejected-through-gitops': 'rejected',
    'readiness-aborted-through-gitops': 'readiness_aborted',
    'missing-traffic-inconclusive-through-gitops': 'inconclusive',
    'missing-telemetry-blocked-through-gitops': 'telemetry_error',
}


def negative_gate(report, job):
    if (report.get('passed') is not True or report['result'] != 'FAILURE' or report['job'] != job or
            report['source']['negative_test_requested'] is not True or
            report['environment_before'] != report['environment_after'] or
            report['artifacts'] != ['output/source.json']):
        raise ValueError('Negative gate report does not prove publication was blocked')
    return FailedBuild(build_number=report['build'], source_commit=report['source']['source_commit'])


def normalize_runtime(item, *, selected):
    final = item['final_response']
    if final['status'] != 200 or final['response']['mode'] != 'healthy':
        raise ValueError('Runtime report has an unhealthy final stable response')
    status = VERDICTS[item['verdict']]
    accepted = selected or item.get('crosscheck_passed') is True
    if selected and (item.get('passed') is not True or item.get('acceptance_passed') is not True or
                     item['stable_non_200'] or item['reported_high_critical'] != 0):
        raise ValueError('Selected runtime acceptance did not pass')
    candidate = item.get('candidate_hash') or (item['serving_hash'] if status == 'promoted' else None)
    if selected and not candidate:
        raise ValueError('Selected runtime report lacks candidate identity')
    if status != 'promoted' and (item['serving_hash'] != item['previous_stable_hash'] or
            final['response']['revision'] != item['baseline_response']['response']['revision']):
        raise ValueError('Fault candidate changed stable identity')
    return ReleaseObservation(
        build_number=item['jenkins_build'], source_commit=item['source_commit'], image=item['image'],
        environment_commit=item['environment_commit'], candidate_hash=candidate,
        status=status, observed_at=item['decision_observed'], stable_revision=final['response']['revision'],
        stable_hash=item['serving_hash'], reported_high_critical=0 if selected else None,
        scanned_image_id=item.get('scanned_image_id'),
        artifacts=item.get('artifact_sha256', {}), analyses=item.get('analyses', []),
        quality='accepted' if selected else ('historical' if accepted else 'excluded'),
        stable_requests=item['stable_requests'], stable_non_200=item['stable_non_200'],
        observation_details={'scenario': item['scenario'], 'raw_trial': item['raw_trial'],
                             'exclusion_reason': item.get('crosscheck_error'),
                             'sampling_quality': item.get('sampling_quality'),
                             'availability_boundary': item.get('availability_boundary')})


def normalize(kind, report):
    if report.get('passed') is not True:
        raise ValueError('Only curated passing report envelopes are supported')
    if kind == 'recovery_target':
        target = normalize_runtime(report['target'], selected=True)
        if target.status != 'promoted' or not target.scanned_image_id or not any(a.phase == 'Successful' for a in target.analyses):
            raise ValueError('Recovery target lacks bound image scan or successful analysis')
        return [target]
    if kind == 'ci_acceptance':
        if report['controller_verdict'] != 'candidate-promoted-through-gitops' or report['reported_high_critical'] != 0:
            raise ValueError('CI report is not an accepted promotion')
        return [ReleaseObservation(
            build_number=report['build'], source_commit=report['source_commit'], image=report['image'],
            environment_commit=report['environment_commit'], candidate_hash=report['serving_hash'], status='promoted',
            observed_at=report['recorded_at_utc'], stable_revision=report['serving_revision'], stable_hash=report['serving_hash'],
            scanned_image_id=report['image_config_id'], reported_high_critical=0, artifacts=report['artifact_sha256'],
            quality='accepted', stable_requests=report['stable_requests'], stable_non_200=report['stable_non_200'],
            observation_details={'raw_trial': report['raw_trial'], 'availability_boundary': report['availability_boundary']})]
    selected = report['trials']
    if len(selected) != 6 or {x['scenario'] for x in selected} != {
            'error', 'latency', 'startup', 'telemetry-outage', 'no-traffic', 'healthy'}:
        raise ValueError('Runtime acceptance requires all six distinct cases')
    rows = {x['jenkins_build']: normalize_runtime(x, selected=True) for x in selected}
    for item in report['attempt_history']:
        if item['jenkins_build'] not in rows:
            rows[item['jenkins_build']] = normalize_runtime(item, selected=False)
    return [rows[number] for number in sorted(rows)]
