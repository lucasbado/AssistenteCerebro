"""Autenticação comum para HTTP e WebSocket (fail closed)."""
import hmac
import os
from urllib.parse import parse_qs
from starlette.responses import JSONResponse

class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and (scope["path"] in ("/", "/health", "/health/") or scope["method"] == "OPTIONS"):
            return await self.app(scope, receive, send)
        esperado = os.getenv("OLLIE_API_TOKEN", "")
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode()
        recebido = authorization[7:] if authorization.startswith("Bearer ") else ""
        if scope["type"] == "websocket" and not recebido:
            protocolos = headers.get(b"sec-websocket-protocol", b"").decode().split(",")
            recebido = next((p.strip()[7:] for p in protocolos if p.strip().startswith("bearer.")), "")
            if not recebido:
                recebido = parse_qs(scope.get("query_string", b"").decode()).get("token", [""])[0]
        if not esperado or not hmac.compare_digest(recebido.encode(), esperado.encode()):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                response = JSONResponse(
                    {"detail": "Autenticação indisponível" if not esperado else "Token inválido"},
                    status_code=503 if not esperado else 401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
