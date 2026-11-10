"""Ephemeral, role-bound browser sessions; no operator key is retained in a session."""
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

COOKIE = 'release_lab_session'


@dataclass
class BrowserSession:
    key_hash: str
    csrf: str
    expires_wall: float
    expires_mono: float
    last_wall: float
    last_mono: float


class BrowserSessions:
    def __init__(self, *, clock=time.time, monotonic=time.monotonic, lifetime=3600, idle=900, limit=256):
        self.clock, self.monotonic = clock, monotonic
        self.lifetime, self.idle, self.limit = lifetime, idle, limit
        self.sessions = OrderedDict()
        self.attempts = OrderedDict()
        self.lock = threading.RLock()

    def throttle(self, address):
        with self.lock:
            now = self.monotonic()
            attempts = [stamp for stamp in self.attempts.pop(address, []) if now - stamp < 60]
            if len(attempts) >= 10:
                self.attempts[address] = attempts
                raise HTTPException(429, 'Too many sign-in attempts. Try again in a minute.', headers={'Retry-After': '60'})
            self.attempts[address] = attempts + [now]
            while len(self.attempts) > 512:
                self.attempts.popitem(last=False)

    def issue(self, key_hash, old_token=None):
        with self.lock:
            self.revoke(old_token)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            wall, mono = self.clock(), self.monotonic()
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = BrowserSession(
                key_hash, csrf, wall + self.lifetime, mono + self.lifetime, wall, mono)
            while len(self.sessions) > self.limit:
                self.sessions.popitem(last=False)
            return token, csrf

    def lookup(self, token):
        with self.lock:
            if not token or len(token) > 128:
                raise HTTPException(401, 'Sign in to continue')
            digest = hashlib.sha256(token.encode()).hexdigest()
            session = self.sessions.get(digest)
            wall, mono = self.clock(), self.monotonic()
            if session is None or wall >= session.expires_wall or mono >= session.expires_mono or \
                    wall - session.last_wall >= self.idle or mono - session.last_mono >= self.idle:
                self.sessions.pop(digest, None)
                raise HTTPException(401, 'Your session ended. Sign in again.')
            session.last_wall, session.last_mono = wall, mono
            self.sessions.move_to_end(digest)
            return session

    def revoke(self, token):
        if token and len(token) <= 128:
            with self.lock:
                self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)


def same_origin(request):
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if request.url.hostname not in {'127.0.0.1', 'localhost', '::1'} or request.headers.get('origin') != expected:
        raise HTTPException(403, 'A same-origin request is required')


def key_role(settings, digest):
    return next((role for stored, role in settings.api_keys.items() if hmac.compare_digest(stored, digest)), None)


def browser_identity(request, sessions, settings, *, mutation=False):
    token = request.cookies.get(COOKIE)
    session = sessions.lookup(token)
    role = key_role(settings, session.key_hash)
    if role is None:
        sessions.revoke(token)
        raise HTTPException(401, 'Your access is no longer available')
    if mutation:
        same_origin(request)
        supplied = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(session.csrf.encode(), supplied.encode()):
            raise HTTPException(403, 'A valid session request token is required')
    return session, role


def mount_browser(app, settings):
    sessions = BrowserSessions()
    app.state.browser_sessions = sessions

    @app.middleware('http')
    async def browser_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    @app.post('/auth/session')
    async def sign_in(request: Request):
        same_origin(request)
        sessions.throttle(request.client.host if request.client else 'local')
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Send the access key as JSON')
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > 4096:
                raise HTTPException(413, 'Sign-in request is too large')
            chunks.append(chunk)
        try:
            payload = json.loads(b''.join(chunks))
            if not isinstance(payload, dict) or set(payload) != {'key'} or not isinstance(payload['key'], str) or not 32 <= len(payload['key']) <= 1024:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, 'Enter a valid access key')
        digest = hashlib.sha256(payload['key'].encode()).hexdigest()
        role = key_role(settings, digest)
        if role is None:
            raise HTTPException(401, 'That access key was not recognized')
        token, csrf = sessions.issue(digest, request.cookies.get(COOKIE))
        response = JSONResponse({'role': role, 'csrf_token': csrf})
        response.set_cookie(COOKIE, token, max_age=3600, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', path='/')
        return response

    @app.get('/auth/session')
    def who_am_i(request: Request):
        session, role = browser_identity(request, sessions, settings)
        return {'role': role, 'csrf_token': session.csrf}

    @app.delete('/auth/session')
    def sign_out(request: Request):
        browser_identity(request, sessions, settings, mutation=True)
        sessions.revoke(request.cookies.get(COOKIE))
        response = JSONResponse({'signed_out': True})
        response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict',
                               secure=request.url.scheme == 'https')
        return response

    import os
    directory = Path(os.environ.get('RELEASE_UI_DIRECTORY', str(Path(__file__).resolve().parents[1] / 'frontend/dist')))

    @app.get('/', include_in_schema=False)
    def portal():
        index = directory / 'index.html'
        if not index.is_file():
            raise HTTPException(503, 'The portal is not available. Contact the lab operator.')
        return FileResponse(index)

    app.mount('/portal', StaticFiles(directory=directory, html=True, check_dir=False), name='portal')
    return sessions
