from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}


def same_origin(origin: str | None, request_url: str) -> bool:
    # CLI clients may omit Origin; an explicit opaque or malformed origin is unsafe.
    if origin is None:
        return True
    try:
        source = urlparse(origin)
        target = urlparse(request_url)
        scheme = {"ws": "http", "wss": "https"}.get(target.scheme, target.scheme)
        return (
            source.scheme in {"http", "https"}
            and source.scheme == scheme
            and source.hostname == target.hostname
            and (source.port or (443 if source.scheme == "https" else 80))
            == (target.port or (443 if scheme == "https" else 80))
            and not source.username and not source.password
            and not source.path and not source.query and not source.fragment
        )
    except ValueError:
        return False


def install_local_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def local_security_headers(request: Request, call_next):
        host = (request.url.hostname or "").lower()
        if host not in LOCAL_HOSTS:
            return JSONResponse({"detail": "OpenAvatar Studio 只接受本机访问"}, status_code=400)

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            if not same_origin(request.headers.get("origin"), str(request.url)) or fetch_site == "cross-site":
                return JSONResponse({"detail": "已阻止来自其他网站的本机写入请求"}, status_code=403)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=(), payment=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: mediastream: https:; "
            "style-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self' https: wss:"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
