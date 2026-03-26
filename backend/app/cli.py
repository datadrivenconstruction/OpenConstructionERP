"""OpenEstimate CLI — run the platform from the command line.

Usage:
    openestimate serve [--host HOST] [--port PORT] [--data-dir DIR]
    openestimate init  [--data-dir DIR]
    openestimate version
    openestimate seed  [--demo]
"""

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".openestimate"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

logger = logging.getLogger("openestimate.cli")

BANNER = r"""
   ____                   ______     __  _                 __
  / __ \____  ___  ____  / ____/____/ /_(_)___ ___  ____ _/ /_____  _____
 / / / / __ \/ _ \/ __ \/ __/ / ___/ __/ / __ `__ \/ __ `/ __/ __ \/ ___/
/ /_/ / /_/ /  __/ / / / /___(__  ) /_/ / / / / / / /_/ / /_/ /_/ / /
\____/ .___/\___/_/ /_/_____/____/\__/_/_/ /_/ /_/\__,_/\__/\____/_/
    /_/                                                    v{version}
"""


def _setup_env(data_dir: Path, host: str, port: int) -> None:
    """Configure environment variables for local-first operation."""
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "openestimate.db"

    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{db_path}")
    os.environ.setdefault("VECTOR_BACKEND", "lancedb")
    os.environ.setdefault("VECTOR_DATA_DIR", str(data_dir / "vectors"))
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("APP_DEBUG", "false")
    os.environ.setdefault("ALLOWED_ORIGINS", f"http://{host}:{port}")
    os.environ.setdefault("JWT_SECRET", "openestimate-local-dev-key")

    # Enable frontend serving
    os.environ["SERVE_FRONTEND"] = "true"


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the OpenEstimate server."""
    data_dir = Path(args.data_dir)
    _setup_env(data_dir, args.host, args.port)

    from app.config import get_settings

    settings = get_settings()
    print(BANNER.format(version=settings.app_version))
    print(f"  Data directory:  {data_dir}")
    print(f"  Database:        {os.environ.get('DATABASE_URL', 'sqlite')}")
    print(f"  Server:          http://{args.host}:{args.port}")
    print(f"  API docs:        http://{args.host}:{args.port}/api/docs")
    print()

    if args.open:
        import threading

        def _open_browser() -> None:
            import time

            time.sleep(2)
            webbrowser.open(f"http://{args.host}:{args.port}")

        threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level="info",
    )


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize data directory and database."""
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "vectors").mkdir(exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)

    print(f"Initialized data directory: {data_dir}")
    print(f"  Database will be at: {data_dir / 'openestimate.db'}")
    print(f"  Vector storage:      {data_dir / 'vectors'}")
    print(f"  Uploads:             {data_dir / 'uploads'}")
    print()
    print("Run 'openestimate serve' to start the server.")


def cmd_version(args: argparse.Namespace) -> None:
    """Print version information."""
    try:
        from app.config import Settings

        version = Settings.model_fields["app_version"].default
    except Exception:
        version = "unknown"

    print(f"OpenEstimate v{version}")
    print(f"Python {sys.version}")


def cmd_seed(args: argparse.Namespace) -> None:
    """Load demo data into the database."""
    data_dir = Path(args.data_dir)
    _setup_env(data_dir, DEFAULT_HOST, DEFAULT_PORT)

    import asyncio

    async def _run_seed() -> None:
        # Initialize database tables
        from app.config import get_settings

        settings = get_settings()
        if "sqlite" in settings.database_url:
            from app.database import Base, engine

            # Import all models
            from app.modules.users import models as _  # noqa: F401
            from app.modules.projects import models as _  # noqa: F401
            from app.modules.boq import models as _  # noqa: F401
            from app.modules.costs import models as _  # noqa: F401

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        print("Database tables created.")

        if args.demo:
            print("Loading demo project data...")
            from app.core.demo_projects import install_demo_project
            from app.database import async_session_factory

            async with async_session_factory() as session:
                result = await install_demo_project(session, "office_tower_berlin")
                await session.commit()
                print(f"Demo project installed: {result.get('project_name', 'OK')}")

        print("Seed complete.")

    asyncio.run(_run_seed())


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="openestimate",
        description="OpenEstimate — open-source construction cost estimation platform",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start the OpenEstimate server")
    serve_p.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind host (default: {DEFAULT_HOST})",
    )
    serve_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT})",
    )
    serve_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    serve_p.add_argument(
        "--open",
        action="store_true",
        help="Open browser after startup",
    )

    # init
    init_p = subparsers.add_parser("init", help="Initialize data directory")
    init_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )

    # version
    subparsers.add_parser("version", help="Show version information")

    # seed
    seed_p = subparsers.add_parser("seed", help="Load seed/demo data")
    seed_p.add_argument(
        "--demo",
        action="store_true",
        help="Install demo project with sample data",
    )
    seed_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "version":
        cmd_version(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command is None:
        # Default: serve with defaults
        args.host = DEFAULT_HOST
        args.port = DEFAULT_PORT
        args.data_dir = str(DEFAULT_DATA_DIR)
        args.open = True
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
