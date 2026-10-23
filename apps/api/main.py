"""Loopback product API. Read APIs expose a sanitized projection, never credentials."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.render_release import ROOT
from .collector import collect, EVIDENCE
from .database import database
from .models import Analysis, AuditEvent, Build, EvidenceRun, InboxEvent, OutboxEvent, Project, Release, RecoveryAttempt
from .service import drain_inbox, ingest, overview


def create_app(url=None, observer=True, evidence_root=EVIDENCE):
    engine, sessions = database(url)
    evidence_root = Path(evidence_root)
    migration_head = ScriptDirectory.from_config(Config(str(ROOT / 'apps/api/alembic.ini'))).get_current_head()

    async def reconcile():
        while True:
            try:
                snapshot = await asyncio.to_thread(collect)
                def persist():
                    with sessions.begin() as session:
                        ingest(session, snapshot)
                        drain_inbox(session)
                await asyncio.to_thread(persist)
                app.state.observer_error = False
            except Exception:
                app.state.observer_error = True
            await asyncio.sleep(20)

    @asynccontextmanager
    async def lifespan(app):
        app.state.observer_error = False
        task = asyncio.create_task(reconcile()) if observer else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        engine.dispose()

    app = FastAPI(title='Releaseboard API', version='0.1.0', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    app.state.sessions = sessions

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/readyz')
    def ready():
        try:
            with engine.connect() as connection:
                if connection.scalar(text('SELECT version_num FROM alembic_version')) != migration_head:
                    raise ValueError('Database migrations are behind the running application')
            return {'status': 'ready'}
        except Exception:
            return JSONResponse({'status': 'database unavailable or unmigrated'}, status_code=503)

    @app.get('/api/overview')
    def summary():
        with sessions() as session:
            result = overview(session)
            result['observer_error'] = getattr(app.state, 'observer_error', False)
            return result

    @app.get('/api/projects')
    def projects():
        with sessions() as session:
            return [{'id': p.id, 'name': p.name, 'repository': p.repository, 'branch': p.branch}
                    for p in session.scalars(select(Project))]

    @app.get('/api/releases')
    def releases():
        with sessions() as session:
            return [{'id': r.id, 'state': r.state, 'version': r.version, **r.data}
                    for r in session.scalars(select(Release).order_by(Release.data['started'].as_string().desc().nullslast()).limit(100))]

    @app.get('/api/builds')
    def builds():
        with sessions() as session:
            return [b.data for b in session.scalars(select(Build).order_by(Build.number.desc()).limit(100))]

    @app.get('/api/analyses')
    def analyses():
        with sessions() as session:
            return [a.data for a in session.scalars(select(Analysis).order_by(Analysis.data['created_at'].as_string().desc().nullslast()).limit(100))]

    @app.get('/api/recoveries')
    def recoveries():
        with sessions() as session:
            return [{'id': r.id, **r.data} for r in session.scalars(select(RecoveryAttempt).order_by(RecoveryAttempt.id.desc()).limit(100))]

    @app.get('/api/evidence')
    def evidence_runs():
        with sessions() as session:
            return [r.data for r in session.scalars(select(EvidenceRun).order_by(EvidenceRun.data['archived_at'].as_string().desc().nullslast()).limit(200))]

    def file_rows(run_id):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', run_id):
            raise HTTPException(404, 'Unknown evidence run')
        try:
            with sqlite3.connect((evidence_root / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
                return db.execute('SELECT name,sha256,size FROM files WHERE run_id=? ORDER BY name', (run_id,)).fetchall()
        except sqlite3.Error:
            raise HTTPException(503, 'Evidence store unavailable')

    @app.get('/api/evidence/{run_id}/files')
    def files(run_id: str):
        rows = file_rows(run_id)
        if not rows:
            raise HTTPException(404, 'Unknown evidence run')
        return [{'name': r[0], 'sha256': r[1], 'size': r[2]} for r in rows]

    @app.get('/api/evidence/{run_id}/files/{sha}')
    def download(run_id: str, sha: str):
        if not re.fullmatch('[a-f0-9]{64}', sha):
            raise HTTPException(404, 'Unknown evidence object')
        row = next((r for r in file_rows(run_id) if r[1] == sha), None)
        path = evidence_root / 'objects' / sha
        if row is None or path.is_symlink() or not path.is_file():
            raise HTTPException(404, 'Unknown evidence object')
        with path.open('rb') as stream:
            if path.stat().st_size != row[2] or hashlib.file_digest(stream, 'sha256').hexdigest() != sha:
                raise HTTPException(409, 'Evidence integrity check failed')
        return FileResponse(path, media_type='application/octet-stream', filename=Path(row[0]).name)

    @app.get('/api/activity')
    def activity():
        with sessions() as session:
            return {'items': [{'id': a.id, 'kind': a.kind, 'actor': a.actor, 'created_at': a.created_at.isoformat(), 'data': a.data}
                              for a in session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(100))],
                    'pending_outbox': session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.delivered_at.is_(None)))}

    @app.post('/api/integrations/events', status_code=202)
    async def callback(request: Request):
        secret = os.environ.get('RELEASE_CALLBACK_SECRET')
        if not secret:
            raise HTTPException(503, 'Callback integration is not configured')
        length = request.headers.get('content-length', '0')
        if not length.isdigit() or int(length) > 262144:
            raise HTTPException(413, 'Event exceeds 256 KiB')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                raise HTTPException(413, 'Event exceeds 256 KiB')
        timestamp = request.headers.get('x-release-timestamp', '')
        event_id = request.headers.get('x-release-event-id', '')
        signature = request.headers.get('x-release-signature', '')
        if not timestamp.isdigit() or len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 300:
            raise HTTPException(401, 'Invalid or expired signature')
        if not re.fullmatch('[A-Za-z0-9._-]{1,128}', event_id):
            raise HTTPException(400, 'Invalid event identity')
        expected = hmac.new(secret.encode(), timestamp.encode() + b'.' + event_id.encode() + b'.' + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, 'sha256=' + expected):
            raise HTTPException(401, 'Invalid or expired signature')
        try:
            value = json.loads(body)
            if (set(value) != {'kind', 'resource_id', 'state'} or not all(isinstance(v, str) and len(v) <= 160 for v in value.values())
                    or value['kind'] not in ('build.observed', 'release.observed')):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, 'Expected kind, resource_id and state; credentials and arbitrary payloads are not accepted')
        digest = hashlib.sha256(body).hexdigest()
        try:
            with sessions.begin() as session:
                existing = session.get(InboxEvent, event_id)
                if existing:
                    if existing.digest != digest:
                        raise HTTPException(409, 'Event identity already refers to a different payload')
                    return {'accepted': True, 'duplicate': True, 'event_id': event_id}
                session.add(InboxEvent(id=event_id, digest=digest, data=value))
        except IntegrityError:
            # A concurrent delivery won. Re-read the durable receipt, including
            # its payload binding; never overwrite an existing event identity.
            with sessions() as session:
                existing = session.get(InboxEvent, event_id)
                if not existing or existing.digest != digest:
                    raise HTTPException(409, 'Conflicting event identity')
            return {'accepted': True, 'duplicate': True, 'event_id': event_id}
        return {'accepted': True, 'duplicate': False, 'event_id': event_id}

    dist = ROOT / 'apps/web/dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='portal')
    return app


def app_factory():
    return create_app()
