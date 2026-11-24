"""Loopback, DNS-rebinding, cross-origin and request-size boundaries."""

import ipaddress
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


class LocalBoundaryMiddleware:
    def __init__(self, app, max_body_bytes=2_000_000):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                script = "'self' 'unsafe-inline'" if scope["path"] == "/docs" else "'self'"
                headers["Content-Security-Policy"] = (
                    f"default-src 'self'; script-src {script}; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                )
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, secure_send)

        peer = scope.get("client")
        if peer:
            try:
                local = ipaddress.ip_address(peer[0]).is_loopback
            except ValueError:
                local = False
            if not local:
                await reject(403, "API доступен только на loopback этого компьютера")
                return

        headers = {key.lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        authority = headers.get(b"host", "")
        try:
            parsed = urlsplit("http://" + authority)
            allowed = (
                len(authority) <= 255 and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and not any(ord(char) <= 32 for char in authority)
            )
        except ValueError:
            allowed = False
        if not allowed:
            await reject(421, "Недопустимый Host: используйте 127.0.0.1 или localhost")
            return

        if scope["path"].startswith("/api/"):
            origin = headers.get(b"origin")
            expected_origin = f"{scope.get('scheme', 'http')}://{authority}"
            if (origin is not None and origin != expected_origin
                    or headers.get(b"sec-fetch-site", "").lower() == "cross-site"):
                await reject(403, "Запросы API с другого origin запрещены")
                return

        if scope["method"] in {"POST", "PATCH", "PUT", "DELETE"}:
            length = headers.get(b"content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    await reject(400, "Некорректный Content-Length")
                    return
                if size < 0:
                    await reject(400, "Некорректный Content-Length")
                    return
                if size > self.max_body_bytes:
                    await reject(413, "Тело запроса превышает 2 МБ")
                    return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > self.max_body_bytes:
                    await reject(413, "Тело запроса превышает 2 МБ")
                    return
                if not message.get("more_body", False):
                    break
            replayed = False

            async def replay_receive():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, secure_send)
        else:
            await self.app(scope, receive, secure_send)
