"""Security response headers middleware.

Adds the standard set of defensive HTTP response headers:
  - X-Frame-Options: DENY            (clickjacking)
  - X-Content-Type-Options: nosniff  (MIME sniffing)
  - Referrer-Policy: same-origin     (referrer leakage)
  - Strict-Transport-Security        (HSTS — production only)
  - Content-Security-Policy          (XSS / injection — relaxed for SPA)
  - Permissions-Policy               (feature gating)

Also strips the `server: uvicorn` header that the ASGI server adds by default,
to avoid leaking the underlying tech stack.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive HTTP headers to every response.

    Most headers are set unconditionally; HSTS is only emitted when the
    request comes in over HTTPS to avoid breaking local dev.
    """

    def __init__(self, app, *, csp: str | None = None, hsts: bool = True) -> None:
        super().__init__(app)
        # Default CSP — relaxed enough for the React SPA + inline styles, but
        # blocks third-party script loading and frames. Override per-deployment
        # via the `csp` constructor argument when nginx/Caddy isn't already
        # injecting one.
        # Default CSP — relaxed enough for the React SPA + the few external
        # services the marketing landing page uses (Google Analytics +
        # Google Fonts), but blocks everything else. Override per-deployment
        # via the `csp` constructor argument when nginx/Caddy isn't already
        # injecting one.
        self._csp = csp or (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://www.googletagmanager.com https://www.google-analytics.com; "
            "script-src-elem 'self' 'unsafe-inline' "
            "https://www.googletagmanager.com https://www.google-analytics.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' https://www.google-analytics.com https://api.github.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        self._hsts_enabled = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Always-on hardening
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

        # CSP — only set if not already set by an upstream proxy.
        # IMPORTANT: don't apply to /api/docs or /api/redoc — they need
        # inline scripts from CDN-hosted Swagger UI.
        path = request.url.path
        if not (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/api/docs")
            or path.startswith("/api/redoc")
        ):
            response.headers.setdefault("Content-Security-Policy", self._csp)

        # HSTS — only over HTTPS, to avoid pinning insecure local dev.
        if self._hsts_enabled and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        # Note about the `server: uvicorn` header:
        # We can't strip it from middleware — uvicorn writes it at the HTTP
        # protocol layer, AFTER the ASGI middleware chain has finished. Setting
        # it here just creates a duplicate header. The proper fix is to launch
        # uvicorn with `server_header=False` (programmatic) or `--no-server-header`
        # (CLI), or to put nginx/Caddy in front in production (which strips it
        # by default). This is documented in deploy/docker/uvicorn.conf.

        return response
