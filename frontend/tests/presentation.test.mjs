import test from 'node:test';
import assert from 'node:assert/strict';
import { scanSummary, metricValue, observationSummary, freshnessName, relative } from '../src/presentation.mjs';

test('missing scan evidence is never converted into zero findings', () => {
  assert.deepEqual(scanSummary(null), { text: 'Not recorded', tone: 'muted' });
  assert.equal(scanSummary({ reported_high_critical: null }).tone, 'muted');
  assert.equal(scanSummary({ reported_high_critical: 0 }).tone, 'good');
  assert.equal(scanSummary({ reported_high_critical: 2 }).tone, 'bad');
});
test('empty and invalid metric vectors stay unknown', () => {
  for (const value of ['[]', '[null]', '["NaN"]', 'invalid', '[1,2]'])
    assert.equal(metricValue({ name: 'candidate-error-ratio', measurements: [{ value }] }), 'No result');
});
test('real candidate ratio and latency values retain their units', () => {
  assert.equal(metricValue({ name: 'candidate-error-ratio', measurements: [{ value: '[1]' }] }), '100%');
  assert.equal(metricValue({ name: 'candidate-p95-latency', measurements: [{ value: '[0.975]' }] }), '0.975 s');
});
test('excluded HTTP samples never become accepted because every response was 200', () => {
  assert.equal(observationSummary({ quality: 'excluded', stable_requests: 357, stable_non_200: 0 }), 'Excluded from acceptance');
  assert.equal(observationSummary({ quality: 'not_measured', stable_requests: 0, stable_non_200: 0 }), 'Not measured');
});
test('freshness distinguishes API, source and historical states', () => {
  assert.equal(freshnessName('api_unavailable'), 'API unavailable');
  assert.equal(freshnessName('unavailable'), 'Source unavailable');
  assert.equal(freshnessName('historical'), 'Historical evidence');
  assert.equal(relative(null), 'Not observed yet');
});
