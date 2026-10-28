import os

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from app.auth.context import actor_context
from app.domain.errors import DomainError
from app.services.officer_service import OfficerService


SESSION_COOKIE = 'suspect_officer_session'
_PUBLIC = frozenset({
    '/api/health',
    '/api/v1/auth/login', '/api/v1/auth/session', '/api/v1/auth/unlock', '/api/v1/auth/logout',
    '/api/v1/client-context', '/api/v1/capabilities', '/api/v1/tls/ca', '/api/v1/tls/ca.crt',
})


def request_token(connection: HTTPConnection) -> str | None:
    authorization = connection.headers.get('authorization', '')
    if authorization.lower().startswith('bearer '):
        return authorization[7:].strip()
    return connection.cookies.get(SESSION_COOKIE)


class OfficerAuthMiddleware:
    """Authenticate API/audio connections without trusting client actor-id fields.

    Legacy preview remains accessible until the first enabled administrator is
    provisioned. Provisioning then enables enforcement automatically. An explicit
    required flag can fail closed before provisioning, never disable an existing
    administrator's protection.
    """
    def __init__(self, app, *, session_factory, required: bool | None = None):
        self.app = app
        self.session_factory = session_factory
        self.required = (os.getenv('SUSPECT_AUTH_REQUIRED', '').strip().lower() in {'1', 'true', 'yes'}) if required is None else required

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        path = scope.get('path', '')
        protected = path.startswith(('/api/', '/work/', '/ws/', '/media/')) and path.rstrip('/') not in _PUBLIC
        if scope.get('method') == 'OPTIONS':
            protected = False
        token = request_token(connection)
        actor = None
        try:
            with self.session_factory() as db:
                service = OfficerService(db)
                configured = service.configured()
                enforce = bool(self.required or configured)
                scope.setdefault('state', {})['officer_auth_required'] = enforce
                scope['state']['officer_auth_configured'] = configured
                authenticate_token = protected or path in {
                    '/api/v1/auth/session', '/api/v1/auth/unlock', '/api/v1/auth/logout',
                }
                if token and authenticate_token:
                    actor = service.authenticate(token, allow_locked=not protected)
                elif protected and enforce:
                    raise DomainError('AUTH_SESSION_REQUIRED', '请先验证民警身份', 401)
        except DomainError as exc:
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 4403 if exc.status_code == 423 else 4401, 'reason': exc.code})
            else:
                response = JSONResponse({'ok': False, 'code': exc.code, 'message': exc.message, 'data': exc.data}, status_code=exc.status_code)
                await response(scope, receive, send)
            return
        reset = actor_context.set(actor)
        try:
            if scope['type'] == 'websocket' and protected:
                async def recheck():
                    try:
                        with self.session_factory() as db:
                            service = OfficerService(db)
                            if token:
                                service.authenticate(token)
                            elif self.required or service.configured():
                                raise DomainError('AUTH_SESSION_REQUIRED', '请先验证民警身份', 401)
                    except DomainError as exc:
                        code = 4403 if exc.status_code == 423 else 4401
                        await send({'type': 'websocket.close', 'code': code, 'reason': exc.code})
                        raise WebSocketDisconnect(code=code) from exc

                async def checked_receive():
                    message = await receive()
                    if message['type'] != 'websocket.disconnect':
                        await recheck()
                    return message

                async def checked_send(message):
                    if message['type'] == 'websocket.send':
                        await recheck()
                    await send(message)

                try:
                    await self.app(scope, checked_receive, checked_send)
                except WebSocketDisconnect:
                    pass
            else:
                await self.app(scope, receive, send)
        finally:
            actor_context.reset(reset)
