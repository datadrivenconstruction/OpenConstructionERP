"""Serve frontend static files from the installed package or dev build.

When running via `openestimate serve` or with SERVE_FRONTEND=true,
the FastAPI app serves the pre-built React frontend directly — no Nginx needed.

Frontend is found in two locations (checked in order):
1. app/_frontend_dist/ — bundled inside the Python wheel (pip install)
2. ../frontend/dist/   — development mode (repo checkout)
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)


def get_frontend_dir() -> Path:
    """Find the bundled frontend dist directory.

    Returns:
        Path to the directory containing index.html and assets/.

    Raises:
        FileNotFoundError: If no frontend build is found.
    """
    # Option 1: installed as package (pip install openestimate)
    pkg_dir = Path(__file__).parent / "_frontend_dist"
    if pkg_dir.is_dir() and (pkg_dir / "index.html").exists():
        return pkg_dir

    # Option 2: development — frontend/dist relative to repo root
    repo_root = Path(__file__).resolve().parent.parent.parent  # backend/app/../../
    dev_dist = repo_root / "frontend" / "dist"
    if dev_dist.is_dir() and (dev_dist / "index.html").exists():
        return dev_dist

    raise FileNotFoundError(
        "Frontend dist not found. "
        "Run 'npm run build' in frontend/ or install the openestimate wheel."
    )


def mount_frontend(app: FastAPI) -> None:
    """Mount frontend static files on the FastAPI app.

    Serves:
    - /assets/* — hashed JS/CSS bundles (long cache)
    - /favicon.svg, /logo.svg — static resources
    - /* (catch-all) — index.html for SPA routing
    """
    try:
        frontend_dir = get_frontend_dir()
    except FileNotFoundError:
        logger.warning("Frontend dist not found — serving API only")
        return

    logger.info("Serving frontend from %s", frontend_dir)

    # Serve hashed assets (JS, CSS)
    assets_dir = frontend_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    # Serve individual static files
    index_path = frontend_dir / "index.html"

    for static_name in ("favicon.svg", "logo.svg"):
        static_path = frontend_dir / static_name
        if static_path.exists():
            # Use a factory to capture the correct path in the closure
            def _make_static_handler(fpath: Path):  # noqa: ANN202
                async def _handler():  # noqa: ANN202
                    return FileResponse(str(fpath))
                return _handler

            app.get(f"/{static_name}", include_in_schema=False)(
                _make_static_handler(static_path)
            )

    # SPA catch-all: any route not matched by /api/* or /assets/* → index.html
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        """Serve index.html for all frontend routes (SPA routing)."""
        return FileResponse(str(index_path))
