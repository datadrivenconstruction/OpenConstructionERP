"""Tests for SecurityHeadersMiddleware.

We pin two things:
  1. The middleware actually emits the headers we claim it does (the
     headline defensive set: X-Frame-Options, CSP, HSTS-on-https, etc.).
  2. The CSP includes the key directives we depend on — frame-ancestors
     'none', no third-party script-src besides the analytics whitelist,
     etc. — so a future "let's relax CSP" change is a deliberate edit
     to this test, not a silent regression.

The middleware is the SOURCE OF TRUTH for CSP — nginx no longer adds
its own CSP header (see deploy/docker/nginx.conf), so this test is
the only enforcement point.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/api/docs")
    async def docs_stub() -> dict[str, str]:
        return {"ok": "docs"}

    return TestClient(app)


def test_basic_defensive_headers_present(client: TestClient) -> None:
    r = client.get("/ping")
    assert r.status_code == 200
    # SAMEORIGIN (not DENY): the app frames its own PDF previews; cross-origin
    # framing is still refused.
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "same-origin"
    assert "geolocation=()" in r.headers.get("Permissions-Policy", "")


def test_csp_header_present_and_has_key_directives(client: TestClient) -> None:
    r = client.get("/ping")
    csp = r.headers.get("Content-Security-Policy")
    assert csp is not None, "CSP must be set by the middleware (sole source of truth)"

    # Core directives we rely on for XSS / clickjacking protection.
    assert "default-src 'self'" in csp
    # SAMEORIGIN-equivalent: same-origin framing is allowed (in-app PDF
    # previews), cross-origin framing is refused. A change back to 'none' would
    # blank every data:/blob: PDF iframe, so it must be a deliberate edit here.
    assert "frame-ancestors 'self'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp

    # In-app PDF previews render a data:/blob: URL in an iframe, so frame-src
    # must allow those schemes (otherwise it falls back to default-src 'self').
    assert "frame-src 'self' blob: data:" in csp

    # Confirm we still allow the analytics hosts the SPA uses.
    # If anyone tightens CSP they should update this test too.
    assert "https://www.googletagmanager.com" in csp

    # The app serves its own typefaces from /assets/vendor/fonts/, so no font
    # host belongs in this policy at all. These used to sit on style-src,
    # font-src and connect-src (the last because the service worker precached
    # the files with fetch()). A policy that still permits them would let a
    # stray third-party font URL work again without anyone noticing, which is
    # what self-hosting was meant to end - so assert their absence everywhere.
    assert "https://fonts.googleapis.com" not in csp
    assert "https://fonts.gstatic.com" not in csp

    # 'self' is what now covers the stylesheet and the font files.
    assert "font-src 'self' data:;" in csp
    assert "style-src 'self' 'unsafe-inline';" in csp


def test_csp_frames_the_privacy_enhanced_video_host_only(client: TestClient) -> None:
    """The Videos page plays tutorials in an iframe from the no-cookie host.

    Without the host on frame-src the player renders blank. Only the no-cookie
    host is allowed: the regular host sets tracking cookies on embed, which is
    the reason the page uses the other one.
    """
    r = client.get("/ping")
    csp = r.headers["Content-Security-Policy"]
    frame_src = next(d for d in csp.split(";") if d.strip().startswith("frame-src"))

    assert "https://www.youtube-nocookie.com" in frame_src.split()
    assert "https://www.youtube.com" not in frame_src.split()


def test_csp_skipped_for_swagger_docs(client: TestClient) -> None:
    """Swagger UI needs inline scripts from a CDN, so we skip CSP on docs paths."""
    r = client.get("/api/docs")
    assert r.headers.get("Content-Security-Policy") is None


def test_hsts_only_on_https() -> None:
    """HSTS must NOT be set on plain-HTTP requests (would brick local dev)."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=True)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(app)
    r = client.get("/ping")  # http
    assert r.headers.get("Strict-Transport-Security") is None


def test_custom_csp_override() -> None:
    """Constructor-injected CSP must win over the default."""
    app = FastAPI()
    custom = "default-src 'none'"
    app.add_middleware(SecurityHeadersMiddleware, csp=custom)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.headers.get("Content-Security-Policy") == custom
