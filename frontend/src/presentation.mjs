export const statusNames = {
  promoted: 'Promoted', rejected: 'Rejected', readiness_aborted: 'Readiness aborted',
  inconclusive: 'Inconclusive', telemetry_error: 'Telemetry error', aborted: 'Aborted',
  progressing: 'In progress', published: 'Published', SUCCESS: 'CI passed', FAILURE: 'CI failed',
  proposed: 'Proposed', applying: 'Applying', verifying: 'Verifying', recovered: 'Recovered', failed: 'Failed', superseded: 'Superseded',
};

export function label(status) { return statusNames[status] || status || 'Unknown'; }
export function tone(status) {
  if (['promoted', 'SUCCESS', 'Successful', 'accepted', 'current', 'recovered'].includes(status)) return 'good';
  if (['rejected', 'readiness_aborted', 'aborted', 'FAILURE', 'Failed', 'failed'].includes(status)) return 'bad';
  if (['inconclusive', 'telemetry_error', 'Error', 'Inconclusive', 'excluded', 'stale', 'unavailable', 'api_unavailable', 'historical', 'proposed', 'applying', 'verifying'].includes(status)) return 'warn';
  return 'muted';
}
export function scanSummary(artifact) {
  const value = artifact?.reported_high_critical;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return { text: 'Not recorded', tone: 'muted' };
  return { text: `${value} high / critical`, tone: value === 0 ? 'good' : 'bad' };
}
export function metricValue(metric) {
  const values = metric?.measurements || [];
  const measurement = values.at(-1);
  if (!measurement) return 'Not measured';
  try {
    const parsed = JSON.parse(measurement.value);
    if (!Array.isArray(parsed) || parsed.length !== 1 || typeof parsed[0] !== 'number' || !Number.isFinite(parsed[0])) return 'No result';
    if (metric.name.includes('error-ratio')) return `${Number((parsed[0] * 100).toFixed(2))}%`;
    if (metric.name.includes('latency')) return `${Number(parsed[0].toFixed(4))} s`;
    return String(parsed[0]);
  } catch { return 'No result'; }
}
export function observationSummary(observation) {
  if (observation.quality === 'excluded') return 'Excluded from acceptance';
  if (!observation.stable_requests) return 'Not measured';
  if (observation.quality === 'accepted' && observation.stable_non_200 === 0) return 'Accepted sample';
  return observation.quality === 'historical' ? 'Historical sample' : 'Recorded sample';
}
export function freshnessName(value) {
  return { current: 'Current observation', stale: 'Observation stale', historical: 'Historical evidence',
    unavailable: 'Source unavailable', api_unavailable: 'API unavailable', unknown: 'State unknown' }[value] || 'State unknown';
}
export function short(value, size = 12) { return value ? value.slice(0, size) : 'Not recorded'; }
export function relative(value, now = Date.now()) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not observed yet';
  const seconds = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
