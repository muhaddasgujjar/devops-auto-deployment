import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { api, ApiError } from './api';
import { label, tone, scanSummary, metricValue, observationSummary, freshnessName, short, relative } from './presentation.mjs';
import type { Audit, Build, Data, Environment, Release, Session } from './types';
import './style.css';

const iconPaths: Record<string, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  releases: <><path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
  build: <><path d="m14 6 4-3 3 3-3 4M13 7l4 4-9 9H4v-4l9-9Z"/><path d="m5 3 4 4M3 5l4 4"/></>,
  audit: <><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M9 9h6M9 13h6M9 17h4"/></>,
  arrow: <><path d="M5 12h14m-5-5 5 5-5 5"/></>,
  refresh: <><path d="M20 7V3l-3 3a8 8 0 1 0 2 11M20 3h-5"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  shield: <><path d="m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5l8-3Z"/><path d="m8 11 3 3 5-6"/></>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  back: <path d="M20 12H4m6-6-6 6 6 6"/>,
  logout: <><path d="M9 4H4v16h5M13 12h8m-4-4 4 4-4 4"/></>,
  key: <><circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-5-5 3-3m-6 0 3-3"/></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
  git: <><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10m12-10c0 6-12 3-12 8"/></>,
  empty: <><path d="m3 8 9-5 9 5v12H3V8Z"/><path d="M3 13h5l2 3h4l2-3h5"/></>,
};
function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name] || iconPaths.info}</svg>;
}
function Brand() { return <span className="brand"><span className="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 9 5v10l-9 5-9-5V7l9-5Z" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="m8 8 4-2 4 2v4l-4 2v4m0-4-4-2V8m4 2 4-2m-4 2L8 8" fill="none" stroke="currentColor" strokeWidth="1.4"/></svg></span>release<span className="brand-light">lab</span></span>; }
function Badge({ value, children }: { value: string; children?: ReactNode }) { return <span className={`badge ${tone(value)}`}><span className="dot"/>{children || label(value)}</span>; }
function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><Icon name="empty"/><h3>{title}</h3><p>{children}</p></div>; }
function Code({ value, onCopy, full = false }: { value?: string | null; onCopy?: (value: string) => void; full?: boolean }) {
  if (!value) return <span className="not-recorded">Not recorded</span>;
  return <span className={`code-value ${full ? 'full' : ''}`}><code title={value}>{full ? value : short(value)}</code>{onCopy && <button className="icon-button" aria-label="Copy value" title="Copy value" onClick={() => onCopy(value)}><Icon name="copy"/></button>}</span>;
}
function date(value?: string | null) { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Not recorded'; }
function useRoute() {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || '/');
  useEffect(() => { const update = () => setRoute(window.location.hash.slice(1) || '/'); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []);
  return route;
}

function SignIn({ onSession, notice }: { onSession: (session: Session) => void; notice: string }) {
  const [key, setKey] = useState(''); const [error, setError] = useState(notice); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!key.trim() || busy) return;
    setBusy(true); setError(''); const supplied = key.trim(); setKey('');
    try { onSession(await api<Session>('/auth/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: supplied }) })); }
    catch (failure) { setError(failure instanceof ApiError && failure.status === 401 ? 'That access key was not recognized.' : (failure as Error).message); }
    finally { setBusy(false); }
  }
  return <main className="login"><section className="login-story"><Brand/><div className="login-heading"><span className="eyebrow">THE DELIVERY CONSOLE</span><h1>Know what shipped.<br/><em>Understand why.</em></h1><p>A clear view of the release you want, the version serving traffic, and the evidence behind each decision.</p><div className="story-flow"><span><Icon name="git"/>Source</span><Icon name="arrow"/><span><Icon name="build"/>Build</span><Icon name="arrow"/><span><Icon name="shield"/>Observe</span></div></div><footer>Release visibility, grounded in evidence.<span className="small-square"/></footer></section><section className="login-form-panel"><div className="mobile-brand"><Brand/></div><div className="login-form"><span className="login-lock"><Icon name="key"/></span><h2>Welcome to your release lab</h2><p>Sign in to inspect your environment.</p><form onSubmit={submit}><label htmlFor="access-key">Access key</label><input id="access-key" type="password" name="access-key" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} placeholder="Enter your access key" required aria-describedby="key-help"/><p id="key-help" className="input-help">Use the key issued for your role. Your access stays permission-scoped.</p>{error && <div className="form-error" role="alert"><Icon name="info"/>{error}</div>}<button className="button primary sign-in" disabled={busy || !key.trim()}>{busy ? 'Signing in…' : 'Sign in'}<Icon name="arrow"/></button></form><div className="login-foot"><Icon name="lock"/><span>This portal does not save your access key.</span></div></div><span className="login-version">RELEASE LAB / LOCAL WORKSPACE</span></section></main>;
}

function ReleaseTable({ releases }: { releases: Release[] }) {
  if (!releases.length) return <Empty title="No matching releases">Try another search or wait for a release observation.</Empty>;
  return <div className="table-scroll"><table><thead><tr><th>Release</th><th>Decision</th><th>Source</th><th>Scan evidence</th><th>Observed</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{releases.map(release => { const scan = scanSummary(release.artifact); return <tr key={release.id}><td><a className="release-link" href={`#/releases/${encodeURIComponent(release.id)}`}><span className="release-number">#{release.build.number}</span><span>{release.build.job}</span></a></td><td><Badge value={release.status}/></td><td><span className="source-cell"><Icon name="git"/><code title={release.build.source_commit}>{short(release.build.source_commit, 8)}</code></span></td><td><span className={`scan-label ${scan.tone}`}><Icon name="shield"/>{scan.text}</span></td><td><time title={date(release.observed_at)}>{relative(release.observed_at)}</time></td><td><a className="row-arrow" href={`#/releases/${encodeURIComponent(release.id)}`} aria-label={`View release ${release.build.number}`}><Icon name="chevron"/></a></td></tr>; })}</tbody></table></div>;
}

function Overview({ data, disconnected, onCopy }: { data: Data; disconnected: boolean; onCopy: (value: string) => void }) {
  const env = data.environment; const desired = env.desired; const stable = env.stable;
  const freshness = disconnected ? 'api_unavailable' : env.freshness;
  const synced = desired && stable && desired.id === stable.id;
  const blocked = data.releases.filter(r => ['rejected', 'readiness_aborted', 'inconclusive', 'telemetry_error', 'aborted'].includes(r.status)).length;
  return <><div className="page-heading"><div><span className="eyebrow">ENVIRONMENT / {env.name.toUpperCase()}</span><h1>Environment overview</h1><p>Desired state, serving state, and the decisions between them.</p></div><span className="environment-label"><span className="dot"/>{env.name}</span></div>
    <section className="environment-panel"><div className="panel-top"><div className="panel-title"><Icon name="releases"/><h2>{env.project}</h2><span className="subtle-tag">{env.name}</span></div><Badge value={freshness}>{freshnessName(freshness)}</Badge></div>{!desired && !env.stable_revision ? <Empty title="No release has been recorded">Your environment will appear here after an observation is received.</Empty> : <div className="state-comparison"><div className="release-state serving"><span className="state-caption"><span className={`state-indicator ${freshness !== 'current' ? 'historical-indicator' : ''}`}/>{freshness === 'current' ? 'SERVING TRAFFIC' : 'LAST RECORDED STABLE'}</span><div className="state-number">{stable ? `#${stable.build.number}` : 'Recorded revision'}<span>Stable release</span></div><div className="state-reference"><Icon name="git"/><Code value={stable?.build.source_commit || env.stable_revision?.split('-jenkins-')[0]} onCopy={onCopy}/></div><dl className="compact-meta"><div><dt>Pod hash</dt><dd><Code value={env.stable_hash}/></dd></div><div><dt>Last observed</dt><dd title={date(env.last_observed_at)}>{relative(env.last_observed_at)}</dd></div></dl></div><div className="state-link"><span className={synced ? 'link-confirmed' : 'link-pending'}><Icon name={synced ? 'check' : 'arrow'}/></span><span>{synced ? 'Same release' : 'Separate states'}</span></div><div className="release-state"><span className="state-caption">DESIRED CANDIDATE</span><div className="state-number">{desired ? `#${desired.build.number}` : 'Not recorded'}<span>{desired ? <Badge value={desired.status}/> : 'No candidate'}</span></div><div className="state-reference"><Icon name="git"/><Code value={desired?.build.source_commit} onCopy={onCopy}/></div><dl className="compact-meta"><div><dt>Environment Git</dt><dd><Code value={desired?.environment_commit}/></dd></div><div><dt>Candidate hash</dt><dd><Code value={desired?.candidate_hash}/></dd></div></dl></div></div>}<div className="panel-foot"><Icon name="clock"/><span>Observation: {date(env.last_observed_at)}</span><span className="foot-version">State version {env.version}</span></div></section>
    <div className="summary-grid"><div className="summary-item"><span>Recorded releases</span><strong>{data.releases.length}</strong><span>Latest release records</span></div><div className="summary-item"><span>Promotion blocked</span><strong>{blocked}<Icon name="shield"/></strong><span>Rejected or awaiting clear evidence</span></div><div className="summary-item"><span>Failed CI builds</span><strong>{data.builds.filter(b => b.result === 'FAILURE').length}</strong><span>Publication did not proceed</span></div><div className="summary-item"><span>Serving scan evidence</span><strong className="summary-text">{scanSummary(stable?.artifact).text}</strong><span>Reported findings; missing stays unknown</span></div></div>
    <section className="section-panel"><div className="section-heading"><div><h2>Recent releases</h2><p>Follow each candidate from source to decision.</p></div><a className="text-link" href="#/releases">View all releases <Icon name="arrow"/></a></div><ReleaseTable releases={data.releases.slice(0, 6)}/></section>
    <div className="principle"><Icon name="info"/><span>CI success records publication. Promotion is a separate controller decision.</span><span>Git → Argo CD → Rollouts</span></div></>;
}

function Releases({ releases }: { releases: Release[] }) {
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState('all');
  const filtered = releases.filter(r => (filter === 'all' || r.status === filter) && `${r.build.number} ${r.build.source_commit} ${r.environment_commit} ${label(r.status)}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="page-heading"><div><span className="eyebrow">DELIVERY HISTORY</span><h1>Releases</h1><p>Inspect candidate decisions and the evidence retained for each release.</p></div><span className="record-count">{releases.length} records</span></div><section className="section-panel"><div className="table-toolbar"><label className="search-field"><Icon name="search"/><input aria-label="Search releases" placeholder="Search build, source or commit…" value={search} onChange={e => setSearch(e.target.value)}/></label><select aria-label="Filter release decision" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All decisions</option>{Array.from(new Set(releases.map(r => r.status))).map(status => <option key={status} value={status}>{label(status)}</option>)}</select></div><ReleaseTable releases={filtered}/><div className="table-footer">{filtered.length} matching records · latest 100 releases at most</div></section></>;
}

function BuildHistory({ builds, releases }: { builds: Build[]; releases: Release[] }) {
  const [search, setSearch] = useState('');
  const filtered = builds.filter(b => `${b.number} ${b.source_commit} ${b.job} ${b.result}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="page-heading"><div><span className="eyebrow">SUPPLY CHAIN</span><h1>Builds & artifacts</h1><p>CI outcomes and reported scan evidence, kept separate from promotion.</p></div></div><section className="section-panel"><div className="table-toolbar"><label className="search-field"><Icon name="search"/><input aria-label="Search builds" placeholder="Search build, source or result…" value={search} onChange={e => setSearch(e.target.value)}/></label><span className="subtle">{filtered.length} builds</span></div>{filtered.length ? <div className="table-scroll"><table><thead><tr><th>Build</th><th>CI result</th><th>Source</th><th>Scan evidence</th><th>SBOM</th><th>Release</th></tr></thead><tbody>{filtered.map(build => { const release = releases.find(r => r.build.id === build.id); const scan = scanSummary(build.artifact); return <tr key={build.id}><td><div className="release-link"><strong>#{build.number}</strong><span>{build.job}</span></div></td><td><Badge value={build.result}/></td><td><code title={build.source_commit}>{short(build.source_commit, 8)}</code></td><td><span className={`scan-label ${scan.tone}`}>{scan.text}</span></td><td>{build.artifact?.refs?.['sbom.json'] ? <span className="reference-present"><Icon name="check"/>Hash recorded</span> : <span className="not-recorded">Not recorded</span>}</td><td>{release ? <a className="text-link" href={`#/releases/${release.id}`}>View release <Icon name="arrow"/></a> : <span className="not-recorded">No release</span>}</td></tr>; })}</tbody></table></div> : <Empty title="No matching builds">Try another source or build number.</Empty>}<div className="table-footer">Latest 100 builds at most · scan results reflect recorded evidence</div></section></>;
}

function Details({ release, onCopy }: { release: Release; onCopy: (value: string) => void }) {
  const scan = scanSummary(release.artifact);
  function download() { const url = URL.createObjectURL(new Blob([JSON.stringify(release, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `release-${release.build.number}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  return <><a href="#/releases" className="back-link"><Icon name="back"/>All releases</a><div className="page-heading"><div><span className="eyebrow">RELEASE EVIDENCE</span><h1>Release #{release.build.number} <Badge value={release.status}/></h1><p>{release.build.job} · observed {date(release.observed_at)}</p></div><button className="button secondary" onClick={download}><Icon name="download"/>Download record</button></div>
    <div className="detail-grid"><section className="section-panel"><div className="section-heading"><h2>Release identity</h2><Icon name="git"/></div><dl className="identity-list">{[['Source commit', release.build.source_commit], ['Environment Git', release.environment_commit], ['Candidate hash', release.candidate_hash], ['Registry image digest', release.artifact.image], ['Scanned image ID', release.artifact.scanned_image_id]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd><Code value={value} full onCopy={onCopy}/></dd></div>)}</dl></section><section className="section-panel"><div className="section-heading"><h2>Supply-chain evidence</h2><Icon name="shield"/></div><div className="scan-focus"><span className={`scan-focus-icon ${scan.tone}`}><Icon name="shield"/></span><strong>{scan.text}</strong><p>{scan.tone === 'muted' ? 'A scan result is not present in this release record.' : 'Reported HIGH / CRITICAL findings for the recorded artifact.'}</p></div><div className="artifact-list">{Object.entries(release.artifact.refs || {}).map(([name, hash]) => <div key={name}><span>{name}</span><Code value={hash} onCopy={onCopy}/></div>)}{!Object.keys(release.artifact.refs || {}).length && <p className="subtle">No artifact hashes recorded.</p>}</div><div className="panel-note">Original scan and SBOM files remain in the CI archive. This view retains their recorded hashes.</div></section></div>
    <section className="section-panel"><div className="section-heading"><div><h2>Candidate analysis</h2><p>Results belong to this candidate, not an earlier release.</p></div></div>{release.analyses.length ? release.analyses.map(analysis => <div className="analysis" key={analysis.id}><div className="analysis-heading"><code>{analysis.name}</code><Badge value={analysis.phase}>{analysis.phase}</Badge></div><div className="metric-grid">{(analysis.data.metrics || []).map(metric => <div className="metric" key={metric.name}><span>{metric.name === 'candidate-error-ratio' ? 'HTTP error ratio' : metric.name === 'candidate-p95-latency' ? 'P95 latency' : metric.name}</span><strong>{metricValue(metric)}</strong><Badge value={metric.phase}>{metric.phase}</Badge>{metric.measurements?.at(-1)?.message && <details><summary>Provider message</summary><pre>{metric.measurements.at(-1)?.message}</pre></details>}</div>)}</div></div>) : <Empty title="No analysis result recorded">A readiness timeout can abort a candidate before analysis starts.</Empty>}</section>
    <section className="section-panel"><div className="section-heading"><div><h2>Stable-service observations</h2><p>Finite client samples, not a production availability guarantee.</p></div></div><div className="observations">{release.observations.map(observation => <article className={`observation ${observation.quality === 'excluded' ? 'excluded-observation' : ''}`} key={observation.id}><div className="observation-heading"><Badge value={observation.quality}>{observationSummary(observation)}</Badge><time>{date(observation.data.observed_at)}</time></div>{observation.quality === 'excluded' && <div className="observation-warning"><Icon name="info"/>{observation.data.exclusion_reason || 'This observation is excluded from acceptance.'}</div>}<div className="observation-stats"><div><span>Stable requests</span><strong>{observation.stable_requests || 'Not measured'}</strong></div><div><span>Non-200 responses</span><strong>{observation.stable_requests ? observation.stable_non_200 : 'Not measured'}</strong></div><div className="observation-revision"><span>Serving revision</span><Code value={observation.data.stable_revision} full onCopy={onCopy}/></div></div>{observation.data.availability_boundary && <p className="observation-boundary">{observation.data.availability_boundary}</p>}</article>)}{!release.observations.length && <Empty title="No client observations recorded"/>}</div></section></>;
}

function AuditTrail({ entries, allowed }: { entries: Audit[]; allowed: boolean }) {
  if (!allowed) return <><div className="page-heading"><div><span className="eyebrow">ACCOUNTABILITY</span><h1>Audit trail</h1></div></div><section className="section-panel"><div className="permission-empty"><Icon name="lock"/><h2>Admin access required</h2><p>Your role can inspect releases and builds. Audit records require an admin session.</p><a className="text-link" href="#/">Back to overview <Icon name="arrow"/></a></div></section></>;
  return <><div className="page-heading"><div><span className="eyebrow">ACCOUNTABILITY</span><h1>Audit trail</h1><p>Durable ingestion, state changes, and source availability.</p></div><span className="record-count">Latest {entries.length} events</span></div><section className="section-panel"><div className="audit-list">{entries.map(entry => <article key={entry.id} className="audit-entry"><div className={`audit-icon ${entry.action === 'source_unavailable' ? 'warn' : 'muted'}`}><Icon name={entry.action === 'source_unavailable' ? 'info' : 'audit'}/></div><div className="audit-content"><div><h3>{entry.action === 'source_unavailable' ? 'Source unavailable' : 'Evidence received'}</h3><span className="subtle-tag">v{entry.version}</span></div><p><code>{entry.data.actor || 'Not recorded'}</code><span>·</span>{entry.data.source || 'Unknown source'}</p>{entry.data.detail && <p>{entry.data.detail}</p>}{entry.data.changes?.map((change, index) => <div key={index} className="audit-change"><span>Build #{change.build}</span><Badge value={change.status || 'unknown'}/><span>{change.state_applied ? 'State applied' : 'State unchanged'}</span>{change.quality === 'excluded' && <span className="excluded-text">Excluded observation</span>}</div>)}</div><time>{date(entry.created_at)}</time></article>)}{!entries.length && <Empty title="No audit records yet"/>}</div></section></>;
}

function App() {
  const [session, setSession] = useState<Session | null>(); const [notice, setNotice] = useState('');
  const [data, setData] = useState<Data | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(''); const [logoutError, setLogoutError] = useState('');
  const controller = useRef<AbortController | null>(null); const generation = useRef(0); const route = useRoute();
  function expired(message: string) { generation.current++; controller.current?.abort(); setSession(null); setData(null); setError(''); setNotice(message); window.location.hash = '/'; }
  const refresh = useCallback(async () => {
    const requestId = ++generation.current; controller.current?.abort(); const active = new AbortController(); controller.current = active;
    setBusy(true);
    try {
      const identity = await api<Session>('/auth/session', { signal: active.signal });
      const [environment, releases, builds, audit] = await Promise.all([
        api<Environment>('/environment', { signal: active.signal }), api<Release[]>('/releases?limit=100', { signal: active.signal }),
        api<Build[]>('/builds?limit=100', { signal: active.signal }), identity.role === 'admin' ? api<Audit[]>('/audit?limit=100', { signal: active.signal }).catch(failure => { if (failure instanceof ApiError && failure.status === 403) return null; throw failure; }) : Promise.resolve(null),
      ]);
      if (requestId !== generation.current) return;
      setSession(identity); setData({ environment, releases, builds, audit: audit || [], auditAllowed: audit !== null, loadedAt: new Date().toISOString() }); setError('');
    } catch (failure) {
      if (requestId !== generation.current || (failure as Error).name === 'AbortError') return;
      if (failure instanceof ApiError && failure.status === 401) expired(failure.message);
      else setError((failure as Error).message);
    } finally { if (requestId === generation.current) setBusy(false); }
  }, []);
  useEffect(() => { api<Session>('/auth/session').then(setSession).catch(failure => { setSession(null); if (!(failure instanceof ApiError) || failure.status !== 401) setNotice('The API is unavailable. Start the service and try again.'); }); }, []);
  const signedIn = Boolean(session);
  useEffect(() => {
    if (!signedIn) return;
    void refresh();
    const timer = setInterval(() => { if (!document.hidden) void refresh(); }, 15000);
    const focus = () => { if (!document.hidden) void refresh(); };
    document.addEventListener('visibilitychange', focus);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', focus); generation.current++; controller.current?.abort(); };
  }, [signedIn, refresh]);
  useEffect(() => { if (toast) { const timer = setTimeout(() => setToast(''), 2500); return () => clearTimeout(timer); } }, [toast]);
  async function copy(value: string) { try { await navigator.clipboard.writeText(value); setToast('Copied to clipboard'); } catch { setToast('Copy is unavailable in this browser'); } }
  async function signOut() {
    if (!session) return;
    try { await api('/auth/session', { method: 'DELETE', headers: { 'X-CSRF-Token': session.csrf_token } }); expired(''); }
    catch (failure) { if (failure instanceof ApiError && failure.status === 401) expired(''); else setLogoutError('Sign-out failed. Try again.'); }
  }
  if (session === undefined) return <main className="boot"><Brand/><p>Connecting to your release lab…</p></main>;
  if (!session) return <SignIn notice={notice} onSession={identity => { setNotice(''); setLogoutError(''); setSession(identity); setData(null); window.location.hash = '/'; }}/>;
  const view = route.startsWith('/releases') ? 'releases' : route.startsWith('/builds') ? 'builds' : route.startsWith('/audit') ? 'audit' : 'overview';
  const detailId = route.startsWith('/releases/') ? route.slice('/releases/'.length) : undefined;
  const selected = detailId ? data?.releases.find(r => r.id === detailId) : null;
  const navigation = [['overview', 'Environment', 'grid', '/'], ['releases', 'Releases', 'releases', '/releases'], ['builds', 'Builds & artifacts', 'build', '/builds'], ['audit', 'Audit trail', 'audit', '/audit']];
  return <div className="app-shell"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to content</a><aside className="sidebar"><a href="#/" className="brand-link" aria-label="Release Lab overview"><Brand/></a><div className="workspace"><span className="workspace-icon">RL</span><div><strong>Release workspace</strong><span>Local environment</span></div><span className="workspace-square"/></div><span className="nav-label">WORKSPACE</span><nav aria-label="Workspace navigation">{navigation.map(([key, title, icon, path]) => <a key={key} href={'#' + path} className={view === key ? 'active' : ''} aria-label={title} aria-current={view === key ? 'page' : undefined}><Icon name={icon}/><span>{title}</span>{key === 'audit' && session.role !== 'admin' && <Icon name="lock" className="nav-lock"/>}</a>)}</nav><div className="sidebar-bottom"><span className="sidebar-info"><Icon name="shield"/><span>Evidence-led delivery<br/><small>Observe. Inspect. Understand.</small></span></span><div className="sidebar-version"><span className="dot"/>LOCAL RELEASE LAB</div></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">Workspace<Icon name="chevron"/><strong>{data?.environment.project || 'Environment'}</strong></div><div className="topbar-actions"><span className="role-label"><Icon name="lock"/>{session.role === 'read' ? 'Read access' : session.role === 'admin' ? 'Admin access' : 'Developer access'}</span><span className="avatar">{session.role.slice(0, 2).toUpperCase()}</span><button className="icon-button sign-out" title="Sign out" aria-label="Sign out" onClick={signOut}><Icon name="logout"/></button></div></header><main id="main-content" className="main-content" tabIndex={-1}><div className="utility-row"><span><span className={`dot ${error ? 'offline-dot' : ''}`}/>{error ? 'Refresh unavailable' : busy ? 'Refreshing records…' : data ? `Loaded ${relative(data.loadedAt)}` : 'Loading records…'}</span><button className="button refresh-button" disabled={busy} onClick={() => void refresh()}><Icon name="refresh" className={busy ? 'spinning' : ''}/>{busy ? 'Refreshing' : 'Refresh'}</button></div>{logoutError && <div className="notice error-notice" role="alert">{logoutError}</div>}{error && <div className="notice error-notice" role="alert"><Icon name="info"/><div><strong>Unable to refresh records</strong><p>{error}{data ? ` Last loaded ${date(data.loadedAt)}.` : ''}</p></div></div>}{!data ? (error ? <Empty title="Records are unavailable">Check the API service, then use Refresh to retry.</Empty> : <div className="skeleton" aria-label="Loading environment"><span/><span/><span/></div>) : detailId ? selected ? <Details release={selected} onCopy={copy}/> : <Empty title="Release not in this view"><a className="text-link" href="#/releases">Back to the latest releases</a></Empty> : view === 'releases' ? <Releases releases={data.releases}/> : view === 'builds' ? <BuildHistory builds={data.builds} releases={data.releases}/> : view === 'audit' ? <AuditTrail entries={data.audit} allowed={data.auditAllowed}/> : <Overview data={data} disconnected={Boolean(error)} onCopy={copy}/>}</main><footer className="app-footer"><span>Release Lab</span><span>Recorded evidence · Controller-owned delivery</span></footer></div>{toast && <div className="toast" role="status"><Icon name="check"/>{toast}</div>}</div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
