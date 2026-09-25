# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Security response headers middleware.

Adds the standard set of defensive HTTP response headers:
  - X-Frame-Options: SAMEORIGIN      (clickjacking; allows same-origin PDF preview)
  - X-Content-Type-Options: nosniff  (MIME sniffing)
  - Referrer-Policy: same-origin     (referrer leakage)
  - Strict-Transport-Security        (HSTS - production only)
  - Content-Security-Policy          (XSS / injection - relaxed for SPA)
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
        # Default CSP - relaxed enough for the React SPA + inline styles, but
        # blocks third-party script loading and frames. Override per-deployment
        # via the `csp` constructor argument when nginx/Caddy isn't already
        # injecting one.
        # Default CSP - relaxed enough for the React SPA + the few external
        # services the marketing landing page uses (Google Analytics +
        # Google Fonts), but blocks everything else. Override per-deployment
        # via the `csp` constructor argument when nginx/Caddy isn't already
        # injecting one.
        # The dashboard map uses MapLibre (`react-map-gl/maplibre`), which
        # spawns a Web Worker from a blob: URL and fetches vector tiles
        # from openfreemap + nominatim (geocoding). Both need explicit
        # CSP allow-listing - without `worker-src blob:` MapLibre can't
        # boot at all, and without the connect-src hosts the map stays
        # blank with CSP violations in the console.
        #
        # The Geo Hub 3D globe uses CesiumJS, whose base imagery is
        # OpenStreetMap raster tiles served from ``tile.openstreetmap.org``.
        # Cesium fetches those tiles with ``fetch()`` (so the texture is not
        # WebGL-tainted), which is governed by ``connect-src`` - NOT
        # ``img-src``. Without the host on ``connect-src`` every tile request
        # is blocked ("Connecting to ... violates ... connect-src") and the
        # globe renders solid black, i.e. "shows only space". The legacy
        # ``a/b/c.`` subdomains are covered by the wildcard.
        # PDF previews (Property Development documents, document/sheet preview)
        # render the generated PDF in an iframe via a ``data:application/pdf``
        # (or ``blob:``) URL. Two CSP rules govern that:
        #   * ``frame-src`` must allow ``data:`` / ``blob:`` - it was previously
        #     unset, so the browser fell back to ``default-src 'self'`` and the
        #     preview iframe rendered blank.
        #   * ``frame-ancestors`` is INHERITED by the framed ``data:``/``blob:``
        #     document, so ``'none'`` made that document refuse to be embedded by
        #     its own (same-origin) parent. ``'self'`` still blocks cross-origin
        #     clickjacking while letting the app frame its own previews.
        #
        # No font host appears anywhere in this policy. The app serves its own
        # typefaces from ``/assets/vendor/fonts/``, so ``'self'`` on font-src
        # and style-src covers them, and the service worker precaches them as
        # ordinary same-origin build output. The Google Fonts hosts used to sit
        # on style-src, font-src and connect-src (the last because Workbox
        # precached the files with ``fetch()``, which connect-src governs).
        # Leaving them behind would keep permitting the third-party fetch the
        # self-hosting removed, so they came out with it.
        self._csp = csp or (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: "
            "https://www.googletagmanager.com https://www.google-analytics.com; "
            "script-src-elem 'self' 'unsafe-inline' "
            "https://www.googletagmanager.com https://www.google-analytics.com; "
            "worker-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "style-src-elem 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            # The Videos page plays tutorials from the privacy-enhanced
            # no-cookie host, loaded only after the user presses play. The
            # regular video host is left off on purpose: it sets cookies on
            # embed, which is why the page does not use it.
            "frame-src 'self' blob: data: https://www.youtube-nocookie.com; "
            "connect-src 'self' https://www.google-analytics.com "
            "https://*.google-analytics.com https://*.analytics.google.com "
            "https://api.github.com "
            "https://tiles.openfreemap.org https://*.openfreemap.org "
            "https://nominatim.openstreetmap.org "
            "https://tile.openstreetmap.org https://*.tile.openstreetmap.org "
            # The dashboard site cards and the project weather card fetch
            # Open-Meteo (keyless, no vendor lock-in) straight from the
            # browser. Without these hosts on connect-src the fetch is
            # CSP-blocked and the weather silently renders nothing.
            "https://api.open-meteo.com https://archive-api.open-meteo.com; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        self._hsts_enabled = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Always-on hardening. X-Frame-Options is SAMEORIGIN (not DENY) so the
        # app can frame its own PDF previews (see the frame-ancestors note on
        # the CSP above); cross-origin framing is still refused.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

        # CSP - only set if not already set by an upstream proxy.
        # IMPORTANT: don't apply to /api/docs or /api/redoc - they need
        # inline scripts from CDN-hosted Swagger UI.
        path = request.url.path
        if not (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/api/docs")
            or path.startswith("/api/redoc")
        ):
            response.headers.setdefault("Content-Security-Policy", self._csp)

        # HSTS - only over HTTPS, to avoid pinning insecure local dev.
        if self._hsts_enabled and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        # Note about the `server: uvicorn` header:
        # We can't strip it from middleware - uvicorn writes it at the HTTP
        # protocol layer, AFTER the ASGI middleware chain has finished. Setting
        # it here just creates a duplicate header. The proper fix is to launch
        # uvicorn with `server_header=False` (programmatic) or `--no-server-header`
        # (CLI), or to put nginx/Caddy in front in production (which strips it
        # by default). This is documented in deploy/docker/uvicorn.conf.

        return response
