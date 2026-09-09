# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Serve frontend static files from the installed package or dev build.

When running via `openestimate serve` or with SERVE_FRONTEND=true,
the FastAPI app serves the pre-built React frontend directly - no Nginx needed.

Frontend is found in two locations (checked in order):
1. app/_frontend_dist/ - bundled inside the Python wheel (pip install)
2. ../frontend/dist/   - development mode (repo checkout)
"""

import logging
import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

logger = logging.getLogger(__name__)

# What an operator is told when a UI path cannot be served because there is no
# bundle to serve it from. Two different states, and the answer says which,
# because the way out differs: one is fixed before the next start, the other is
# a build that went missing under a server that is otherwise healthy.
#
# A bare 404 on every path of a running server is its own kind of confusing - it
# reads as "wrong URL" when the truth is "this deployment has no UI in it" - so
# the body names the deployment problem. Deliberately plain text in a JSON
# envelope and not a styled page: the reader is whoever is looking at a curl or
# a browser's network tab during a failed deploy.
_NO_BUNDLE_DETAIL = (
    "This server started without a frontend bundle and is serving the API only. "
    "Build the UI with 'npm run build' in frontend/, or install the openconstructionerp wheel. "
    "The API itself is up, under /api."
)
_LOST_BUNDLE_DETAIL = (
    "The frontend bundle this server mounted at startup is no longer on disk, so the UI cannot be served. "
    "The build directory was removed or replaced while the server was running; restore it and restart. "
    "The API itself is up, under /api."
)


def _bundle_missing_404(detail: str) -> Response:
    """Build the 404 sent when a UI path has no bundle behind it.

    Args:
        detail: Which of the two missing-bundle states this is, in the
            operator's terms.

    Returns:
        A JSON 404 in the same ``{"detail": ...}`` shape FastAPI's own 404 uses,
        so anything already parsing one parses this. Server-side paths stay in
        the log rather than the body - the reader of a 404 is not always the
        operator.
    """
    return JSONResponse(status_code=404, content={"detail": detail})


# Set by ``mount_frontend`` so health checks can report on the dist this
# process actually serves. A live ``get_frontend_dir()`` probe is not enough:
# the disk can hold a rebuilt dist while this process mounted nothing (build
# finished after startup) or mounted a tree whose entry point was deleted by
# a later build - in both cases the UI is down while the disk looks fine.
_mounted_frontend_dir: Path | None = None


def mounted_frontend_intact() -> bool | None:
    """Whether the frontend dist mounted by this process still has index.html.

    Returns:
        True/False for a process that mounted a frontend at startup,
        None when the frontend was never mounted (API-only mode).
    """
    if _mounted_frontend_dir is None:
        return None
    return (_mounted_frontend_dir / "index.html").is_file()


# Pin JavaScript-family MIME types at import time.
#
# ``.bc3`` is here for a different reason than the rest: the stdlib table has no
# entry for it on any host, so it would be served as ``application/octet-stream``.
# The value is the one ``REGISTERED_EXPORTERS`` already declares for a BC3 the
# product writes, so a downloaded sample and an exported budget arrive under the
# same type.
#
# Both ``StaticFiles`` (the ``/assets`` mount) and ``FileResponse`` (the root
# SPA fallback) derive ``Content-Type`` from the stdlib ``mimetypes`` table.
# That table is seeded from the host OS, and on a fresh wheel install it does
# NOT reliably contain ``.mjs`` (Python only added it to the bundled table in
# recent 3.x point releases), while the Windows registry has historically
# mapped ``.js`` to ``text/plain``.  When the worker chunk
# ``/assets/pdf.worker.min-<hash>.mjs`` is then served as ``text/plain`` or
# ``application/octet-stream`` the browser refuses the module import and
# pdf.js fails with "Setting up fake worker failed: Failed to fetch
# dynamically imported module" on /takeoff.  Registering the types here makes
# every served build deterministic regardless of the host's registry state.
# Same root cause as the earlier Vite-PWA ``sw.js`` / ``registerSW.js`` fix.
for _suffix, _mime in (
    (".js", "text/javascript"),
    (".mjs", "text/javascript"),
    (".css", "text/css"),
    (".wasm", "application/wasm"),
    (".json", "application/json"),
    (".svg", "image/svg+xml"),
    (".bc3", "text/plain"),
):
    mimetypes.add_type(_mime, _suffix)


# Suffixes the SPA fallback will serve from the dist root instead of answering
# with index.html. A file whose suffix is not here is not "missing" in any way a
# reader can see: the request comes back 200 carrying the app shell, under the
# asset's own URL, and whatever asked for it fails several steps later.
#
# NB: ``.js``/``.mjs``/``.css``/``.map``/``.wasm`` MUST be here - Vite-PWA emits
# ``registerSW.js``, ``sw.js`` and ``workbox-*.js`` at the dist ROOT (not under
# ``/assets``), and Cesium ships root-level ``.css``/``.wasm``. Without these
# suffixes the browser refused the service worker on a wrong MIME type and the
# PWA never registered.
#
# ``.csv``/``.tsv``/``.xlsx``/``.bc3`` are the sample budgets under
# ``/templates``, which the regional exchange screens link to as "download a
# sample file to try it". ``.bc3`` was the one missing, so on 9 September that
# link answered 200 with index.html under a .bc3 name, and the page's own parser
# read the HTML as a budget and reported positions found in it. Whatever a screen
# offers for download belongs in this set, and
# ``test_shipped_exchange_samples_are_importable`` is what keeps the two in step.
SERVED_ROOT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".ico",
        ".png",
        ".svg",
        ".webmanifest",
        ".json",
        ".txt",
        ".xml",
        ".webp",
        ".avif",
        ".jpg",
        ".jpeg",
        ".gif",
        ".woff",
        ".woff2",
        ".csv",
        ".tsv",
        ".xlsx",
        ".xls",
        ".bc3",
        ".js",
        ".mjs",
        ".css",
        ".map",
        ".wasm",
    }
)


def get_frontend_dir() -> Path:
    """Find the bundled frontend dist directory.

    Returns:
        Path to the directory containing index.html and assets/.

    Raises:
        FileNotFoundError: If no frontend build is found.
    """
    # ``is_file`` rather than ``exists``: the entry point is handed to
    # ``FileResponse``, which raises on anything that is not a regular file, so
    # a directory named index.html would pass resolution here and then 500 on
    # the first request. Resolution has to gate on what the server will need.

    # Option 1: installed as package (pip install openconstructionerp)
    pkg_dir = Path(__file__).parent / "_frontend_dist"
    if pkg_dir.is_dir() and (pkg_dir / "index.html").is_file():
        return pkg_dir

    # Option 2: development - frontend/dist relative to repo root
    repo_root = Path(__file__).resolve().parent.parent.parent  # backend/app/../../
    dev_dist = repo_root / "frontend" / "dist"
    if dev_dist.is_dir() and (dev_dist / "index.html").is_file():
        return dev_dist

    # Name both places. "Missing" means something different in each - an empty
    # wheel in the first, an unbuilt checkout in the second - and an operator
    # who cannot see which one was expected debugs the wrong one.
    raise FileNotFoundError(
        f"Frontend dist not found. Looked for index.html in {pkg_dir} (wheel bundle) "
        f"and {dev_dist} (dev build). Run 'npm run build' in frontend/ or install "
        f"the openconstructionerp wheel."
    )


def _mount_api_only_404(app: FastAPI) -> None:
    """Answer UI paths with a 404 that says this server has no bundle.

    Registered instead of the SPA fallback when no frontend was found. It
    replaces the bare ``{"detail":"Not Found"}`` that a route-less path would
    otherwise get, which reads as a mistyped URL when the truth is that the
    deployment shipped without a UI. The startup warning states this once, and
    an operator who reaches the server through a browser never sees the log.

    Args:
        app: The FastAPI application to register the handler on.
    """
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(404)
    async def _api_only_404(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api"):
            return await http_exception_handler(request, exc)
        return _bundle_missing_404(_NO_BUNDLE_DETAIL)


def mount_frontend(app: FastAPI) -> None:
    """Mount frontend static files on the FastAPI app.

    Serves:
    - /assets/* - hashed JS/CSS bundles (long cache)
    - /favicon.svg, /logo.svg - static resources
    - /* (catch-all via 404 handler) - index.html for SPA routing

    Strategy: instead of a ``/{path:path}`` catch-all route (which competes
    with FastAPI's built-in ``/api/docs``, ``/api/redoc``, and
    ``/api/openapi.json``), we override the **404 exception handler**.
    This guarantees that all real API routes - including Swagger UI - are
    resolved first by FastAPI's normal router.  Only genuinely unmatched
    paths fall through to the 404 handler, which serves ``index.html``
    for non-API paths (SPA client-side routing).

    When no frontend is found at all, a 404 handler is registered anyway (see
    ``_mount_api_only_404``) so UI paths say why they have nothing to serve
    instead of denying the path and leaving the operator to guess.
    """
    try:
        frontend_dir = get_frontend_dir()
    except FileNotFoundError as exc:
        # The message carries both candidate directories, so the log says which
        # kind of install this is rather than only that something is absent.
        logger.warning("Frontend dist not found - serving API only. %s", exc)
        _mount_api_only_404(app)
        return

    global _mounted_frontend_dir
    _mounted_frontend_dir = frontend_dir

    logger.info("Serving frontend from %s", frontend_dir)

    # Everything below is wired against a dist checked once, here, at mount
    # time. That dist can go away under a running server - a redeploy that wipes
    # the build directory, a volume that unmounts, a container image rebuilt in
    # place - and every reader of it reacts by raising rather than 404ing, which
    # the ASGI stack turns into a bare 500 in plain text. That tells the operator
    # the server crashed when the server is fine and a directory is not, and
    # sends them to read application logs for a filesystem problem.
    #
    # Logged once rather than per request: the state is permanent until someone
    # restores the directory, and a line per page load buries it.
    bundle_loss_logged = False

    def _note_bundle_loss() -> None:
        nonlocal bundle_loss_logged
        if not bundle_loss_logged:
            bundle_loss_logged = True
            logger.error(
                "Frontend bundle mounted from %s is gone - answering 404 for UI paths until it is restored",
                frontend_dir,
            )

    # Serve hashed assets (JS, CSS) with year-long immutable caching.
    # Vite emits content-hash suffixes (e.g. index-9MyhyuSS.js) so the
    # URL changes whenever the file changes - repeat visits can serve
    # straight from the browser cache without revalidation.
    class _ImmutableStaticFiles(StaticFiles):
        async def check_config(self) -> None:
            """Do not turn a vanished assets directory into a 500.

            StaticFiles stats its directory once and raises RuntimeError if it
            is not there, and that check runs on the FIRST REQUEST rather than
            at construction. The directory is verified below before mounting, so
            the only thing this check can still catch is the dist disappearing
            afterwards - which ``lookup_path`` already answers honestly as a 404.

            The lazy timing is why this was easy to miss: a server that had
            served one asset before the dist vanished answered 404, because the
            flag gating the check was already set, while a server whose dist
            went missing before its first asset request answered 500. Same
            deployment, opposite diagnosis, decided by traffic order.
            """
            if not Path(str(self.directory)).is_dir():
                _note_bundle_loss()

        async def get_response(self, path: str, scope):  # noqa: ANN001, ANN202
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    assets_dir = frontend_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            _ImmutableStaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    # Serve individual static files at the root (favicon, logo, etc.)
    index_path = frontend_dir / "index.html"

    for static_name in ("favicon.svg", "logo.svg"):
        static_path = frontend_dir / static_name
        if static_path.is_file():
            # Use a factory to capture the correct path in the closure
            def _make_static_handler(fpath: Path):  # noqa: ANN202
                async def _handler() -> Response:
                    if not fpath.is_file():
                        _note_bundle_loss()
                        return _bundle_missing_404(_LOST_BUNDLE_DETAIL)
                    return FileResponse(str(fpath))

                return _handler

            app.get(f"/{static_name}", include_in_schema=False)(_make_static_handler(static_path))

    # Serve other root-level static files (e.g. manifest.json, robots.txt)
    # that may exist in the frontend dist directory. The set is module level so
    # a test can ask what this build will actually hand back.
    _root_static_extensions = SERVED_ROOT_EXTENSIONS

    # ── Conventional API path aliases ────────────────────────────────────
    # k8s liveness/readiness probes, openapi-typescript generators, third-
    # party Swagger UIs - all of these expect ``/health`` and
    # ``/openapi.json`` at the root, not under ``/api``.  Without these
    # redirects the SPA fallback below catches them and returns ``index.html``
    # with HTTP 200, which makes a sick service look healthy to a probe
    # (BUG-002).  Permanent (308) so caching layers and clients pin the
    # canonical path going forward.
    from fastapi.responses import RedirectResponse

    @app.get("/health", include_in_schema=False)
    async def _health_alias() -> Response:
        return RedirectResponse(url="/api/health", status_code=308)

    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi_alias() -> Response:
        return RedirectResponse(url="/api/openapi.json", status_code=308)

    # ── SPA fallback via custom 404 handler ─────────────────────────────
    # Keep a reference to whatever 404 handler was already registered
    # (e.g. FastAPI's default) so we can delegate API 404s to it.
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(404)
    async def _spa_or_404(request: Request, exc: StarletteHTTPException) -> Response:
        """Serve index.html for frontend routes; real 404 for API paths.

        This replaces the previous ``/{path:path}`` catch-all route which
        could shadow FastAPI's built-in ``/api/docs`` and ``/api/redoc``.
        """
        path = request.url.path

        # API paths: return the normal JSON 404 response.
        if path.startswith("/api"):
            return await http_exception_handler(request, exc)

        # Check if the requested file physically exists in the frontend
        # dist (e.g. /robots.txt, /manifest.json).  Serve it directly
        # if it does, to avoid breaking non-HTML static assets.
        relative = path.lstrip("/")
        if relative:
            candidate = frontend_dir / relative
            if candidate.is_file() and candidate.suffix in _root_static_extensions:
                return FileResponse(str(candidate))

            # A request that asks for a FILE and does not get one is a 404, and
            # saying so is the whole point. Falling through to index.html sends
            # HTML with status 200 under an asset's URL, which is the same
            # failure the /health alias above exists to prevent: the caller is
            # told everything is fine and handed something it cannot use.
            #
            # It is not a theoretical tidiness. A browser holding a stale
            # index.html asks for a hashed bundle a redeploy has deleted, gets
            # HTML back with a 200 and a text/html type, and fails inside the
            # module loader. The page then reports a syntax error in a script,
            # which is several steps away from "that file is gone" and is where
            # anyone debugging it starts looking. It also defeats the browser
            # and any proxy in between, both of which treat 200 as a thing worth
            # keeping.
            #
            # Two ways to be asking for a file, and both are needed. The
            # extension set is what catches root-level assets, and everything
            # under the /assets mount is a file request whatever it ends in,
            # since Vite puts nothing else there. SPA routes are unaffected:
            # /projects/123 and /boq have no suffix at all, and a route that
            # does end in a dotted segment keeps its index.html unless that
            # suffix is one we actually serve.
            looks_like_a_file = candidate.suffix in _root_static_extensions or path.startswith("/assets/")
            if looks_like_a_file:
                return await http_exception_handler(request, exc)

        # The app shell has to still be there. See the note beside
        # ``_note_bundle_loss`` above: without this the answer is a 500, and a
        # deployment mistake reads as a crashed server.
        if not index_path.is_file():
            _note_bundle_loss()
            return _bundle_missing_404(_LOST_BUNDLE_DETAIL)

        # Everything else: SPA client-side routing → index.html. Force
        # the browser to revalidate the entry on every reload - a stale
        # cached index.html points at hashed asset URLs that may have
        # been deleted by a redeploy.
        return FileResponse(
            str(index_path),
            headers={"Cache-Control": "no-cache"},
        )
