import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from backend.config import load_settings
from backend.contracts import CallbackRequest, ImportRequest, HealthWindow, RecoveryEvent, MonitoringTick, DeliveryResult
from backend.db import Database
from backend.imports import negative_gate, normalize
from backend.service import Conflict, StateService
from backend.browser import browser_identity, key_role, mount_browser


def content_hash(payload):
    # Optimistic version is transport control, not the identity of a source event.
    content = {key: value for key, value in payload.items() if key != 'expected_version'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def create_app(settings=None):
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app):
        db = Database(settings.database_url)
        app.state.service = StateService(db, settings)
        try:
            yield
        finally:
            db.close()

    app = FastAPI(title='Release Lab State API', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    key_header = APIKeyHeader(name='X-API-Key', auto_error=False)
    sessions = mount_browser(app, settings)

    def authorize(*allowed):
        def dependency(request: Request, token=Depends(key_header)):
            channel = 'api'
            if token is not None:
                if not token or len(token) > 1024:
                    raise HTTPException(401, 'API key required')
                digest = hashlib.sha256(token.encode()).hexdigest()
                role = key_role(settings, digest)
            else:
                session, role = browser_identity(request, sessions, settings,
                    mutation=request.method not in ('GET', 'HEAD', 'OPTIONS'))
                digest, channel = session.key_hash, 'browser'
            if role is None:
                raise HTTPException(401, 'Invalid API key')
            if role not in allowed:
                raise HTTPException(403, 'Role cannot perform this action')
            return channel + ':' + role + ':' + digest[:12]
        return dependency

    read = authorize('read', 'developer', 'admin', 'recovery', 'notifier')
    write = authorize('developer', 'admin')
    admin = authorize('admin')
    recover = authorize('admin', 'recovery')
    notify = authorize('admin', 'notifier')

    from backend.monitoring import MonitoringService

    @app.get('/monitoring', dependencies=[Depends(read)])
    def monitoring(request: Request):
        return MonitoringService(request.app.state.service).snapshot()

    @app.post('/monitoring/tick')
    async def monitoring_tick(request: Request, actor=Depends(notify)):
        try:
            return await run_in_threadpool(MonitoringService(request.app.state.service).tick,
                parse(await body(request), MonitoringTick), actor)
        except ValueError as error:
            if isinstance(error, Conflict): raise
            raise HTTPException(422, str(error))

    @app.post('/notifications/claim')
    def notification_claim(request: Request, actor=Depends(notify)):
        return MonitoringService(request.app.state.service).claim(actor)

    @app.post('/notifications/{notification_id}/result')
    async def notification_result(notification_id: str, request: Request, actor=Depends(notify)):
        try:
            return await run_in_threadpool(MonitoringService(request.app.state.service).finish,
                notification_id, parse(await body(request), DeliveryResult), actor)
        except ValueError as error:
            if isinstance(error, Conflict): raise
            raise HTTPException(422, str(error))

    from backend.recovery import RecoveryService, InvalidRecovery
    from backend.recovery_policy import POLICY

    @app.exception_handler(InvalidRecovery)
    async def invalid_recovery(request, exc):
        return JSONResponse(status_code=422, content={'detail': str(exc)})

    @app.get('/recoveries', dependencies=[Depends(read)])
    def recoveries(request: Request, limit: int = Query(50, ge=1, le=100)):
        return RecoveryService(request.app.state.service).history(limit)

    @app.get('/recovery/policy', dependencies=[Depends(read)])
    def recovery_policy():
        return POLICY

    @app.get('/recovery/health', dependencies=[Depends(read)])
    def health_windows(request: Request, release_id: str, limit: int = Query(3, ge=1, le=100)):
        return RecoveryService(request.app.state.service).windows(release_id, limit)

    @app.post('/recovery/health')
    async def post_health(request: Request, actor=Depends(recover)):
        envelope = parse(await body(request), HealthWindow)
        return await run_in_threadpool(RecoveryService(request.app.state.service).observe, envelope, actor)

    @app.post('/recoveries/{recovery_id}/events')
    async def recovery_event(recovery_id: str, request: Request, actor=Depends(recover)):
        envelope = parse(await body(request), RecoveryEvent)
        return await run_in_threadpool(RecoveryService(request.app.state.service).event, recovery_id, envelope, actor)

    async def body(request):
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > settings.max_body_bytes:
                raise HTTPException(413, 'Request body exceeds the configured limit')
            chunks.append(chunk)
        return b''.join(chunks)

    def parse(raw, contract):
        try:
            json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            return contract.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise HTTPException(422, 'Payload does not match the release evidence contract')

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request, exc):
        return JSONResponse(status_code=503, content={'detail': 'Database unavailable; state was not accepted'})

    @app.get('/health/live')
    def live():
        return {'alive': True}

    @app.get('/health/ready', dependencies=[Depends(read)])
    def ready(request: Request):
        if not request.app.state.service.db.ready():
            raise HTTPException(503, 'Database migration required')
        return {'ready': True}

    @app.get('/environment', dependencies=[Depends(read)])
    def environment(request: Request):
        return request.app.state.service.state()

    @app.get('/releases', dependencies=[Depends(read)])
    def history(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        return request.app.state.service.history(limit, offset)

    @app.get('/releases/{release_id}', dependencies=[Depends(read)])
    def release(request: Request, release_id: str):
        service = request.app.state.service
        with service.db.engine.connect() as conn:
            result = service.release(conn, release_id)
        if result is None:
            raise HTTPException(404, 'Release not found')
        return result

    @app.get('/audit', dependencies=[Depends(admin)])
    def audit(request: Request, limit: int = Query(50, ge=1, le=100)):
        return request.app.state.service.audit(limit)

    @app.get('/builds', dependencies=[Depends(read)])
    def builds(request: Request, limit: int = Query(50, ge=1, le=100)):
        return request.app.state.service.builds(limit)

    @app.get('/openapi.json', dependencies=[Depends(read)])
    def specification():
        document = app.openapi()
        schemas = document.setdefault('components', {}).setdefault('schemas', {})
        # Bodies are streamed manually for size and exact-byte HMAC validation.
        # Publish their actual Pydantic contracts explicitly for API consumers.
        for path, contract in (('/imports', ImportRequest), ('/callbacks', CallbackRequest),
                               ('/recovery/health', HealthWindow), ('/recoveries/{recovery_id}/events', RecoveryEvent)):
            body_schema = contract.model_json_schema(ref_template='#/components/schemas/{model}')
            schemas.update(body_schema.pop('$defs', {}))
            schemas[contract.__name__] = body_schema
            document['paths'][path]['post']['requestBody'] = {'required': True, 'content': {
                'application/json': {'schema': {'$ref': '#/components/schemas/' + contract.__name__}}}}
        document['paths']['/callbacks']['post']['parameters'] = [
            {'in': 'header', 'name': name, 'required': True, 'schema': {'type': 'string'}}
            for name in ('X-Release-Timestamp', 'X-Release-Signature')]
        return document

    @app.post('/imports')
    async def import_evidence(request: Request, actor=Depends(write)):
        raw = await body(request)
        envelope = parse(raw, ImportRequest)
        try:
            failures = [negative_gate(envelope.report, settings.job)] if envelope.kind == 'ci_negative_gate' else []
            observations = [] if failures else normalize(envelope.kind, envelope.report)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, 'Evidence report is incomplete or inconsistent')
        payload = envelope.model_dump(mode='json')
        return await run_in_threadpool(request.app.state.service.ingest,
            external_id='import:' + envelope.event_id, expected_version=envelope.expected_version,
            payload=payload, payload_hash=content_hash(payload), request_hash=hashlib.sha256(raw).hexdigest(),
            releases=observations, failed_builds=failures, actor=actor, source='import')

    @app.post('/callbacks')
    async def callback(request: Request):
        raw = await body(request)
        stamp, supplied = request.headers.get('X-Release-Timestamp', ''), request.headers.get('X-Release-Signature', '')
        try:
            if len(stamp) > 12 or abs(time.time() - int(stamp)) > 300:
                raise ValueError()
        except ValueError:
            raise HTTPException(401, 'Callback timestamp is missing or expired')
        expected = 'v1=' + hmac.new(settings.callback_secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise HTTPException(401, 'Invalid callback signature')
        envelope = parse(raw, CallbackRequest)
        if envelope.release and envelope.release.quality != 'not_measured':
            raise HTTPException(422, 'Callbacks cannot claim curated HTTP experiment acceptance')
        payload = envelope.model_dump(mode='json')
        return await run_in_threadpool(request.app.state.service.ingest,
            external_id='callback:' + envelope.event_id, expected_version=envelope.expected_version,
            payload=payload, payload_hash=content_hash(payload), request_hash=hashlib.sha256(raw).hexdigest(),
            releases=[envelope.release] if envelope.release else [], unavailable=envelope.unavailable,
            actor='signed-collector', source='callback')

    return app
