"""Entry point for PyInstaller / standalone execution.

Usage:
    python -m app                    # Dev mode
    openestimate-server.exe          # Production (PyInstaller bundle)
"""

import os
import sys
import multiprocessing


def main() -> None:
    """Start the OpenConstructionERP backend server."""
    import uvicorn

    # Parse CLI args: --host X --port Y
    host = "127.0.0.1"
    port = 8741
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
        elif arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass

    # Also check env vars as fallback
    host = os.environ.get("HOST", host)
    port = int(os.environ.get("PORT", str(port)))

    # Desktop app mode: serve frontend, production settings
    if getattr(sys, "frozen", False):
        os.environ.setdefault("SERVE_FRONTEND", "1")
        os.environ.setdefault("APP_ENV", "production")
        os.environ.setdefault("APP_DEBUG", "false")

    print(f"Starting OpenConstructionERP on http://{host}:{port}")

    # Use direct app import for PyInstaller compatibility
    from app.main import create_app
    app = create_app()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
