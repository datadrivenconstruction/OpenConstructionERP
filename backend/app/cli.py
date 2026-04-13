"""OpenConstructionERP CLI — run the platform from the command line.

Usage:
    openestimate serve   [--host HOST] [--port PORT] [--data-dir DIR] [--open]
    openestimate init-db [--data-dir DIR]
    openestimate doctor  [--host HOST] [--port PORT] [--data-dir DIR]
    openestimate seed    [--demo] [--data-dir DIR]
    openestimate version

The happy path for a new user is just three commands:

    pip install openconstructionerp
    openestimate init-db
    openestimate serve

`openestimate doctor` runs a set of pre-flight checks and prints OK /
WARNING / ERROR per check so you can diagnose install problems before
opening a GitHub issue.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import webbrowser
from pathlib import Path

# ── Console encoding hardening ────────────────────────────────────────────
# On Windows + Anaconda Python the default console encoding is cp1252,
# which crashes on any non-ASCII character (em-dash, arrow, box-drawing,
# etc.). This is the same family of bug that killed v1.3.9 — silent or
# noisy failure on Windows. We try to switch stdout/stderr to UTF-8 if
# possible; otherwise we fall back to ASCII-only output.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _stdout_supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc

DEFAULT_DATA_DIR = Path.home() / ".openestimate"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MIN_PYTHON = (3, 12)

DOCS_URL = "https://openconstructionerp.com/docs"
TROUBLESHOOTING_URL = "https://openconstructionerp.com/docs#troubleshooting"
ISSUES_URL = "https://github.com/datadrivenconstruction/OpenConstructionERP/issues"

logger = logging.getLogger("openestimate.cli")


# ── ANSI colors (amber accent #f0883e, disabled if no TTY or NO_COLOR) ────
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    # Windows: modern Terminal / PowerShell / Git Bash handle ANSI fine.
    # Legacy cmd.exe does not, but colorama is already a uvicorn transitive
    # dep on Windows, so we can enable it opportunistically.
    if sys.platform == "win32":
        try:
            import colorama

            colorama.just_fix_windows_console()
        except Exception:
            return False
    return True


_COLOR = _supports_color()
_UNICODE = _stdout_supports_unicode()


def _u(unicode_str: str, ascii_fallback: str) -> str:
    """Pick the unicode form when the console can render it, else ASCII."""
    return unicode_str if _UNICODE else ascii_fallback


def _c(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _amber(text: str) -> str:
    # 256-color approximation of the project accent #f0883e
    return _c(text, "38;5;208")


def _green(text: str) -> str:
    return _c(text, "32")


def _red(text: str) -> str:
    return _c(text, "31")


def _yellow(text: str) -> str:
    return _c(text, "33")


def _dim(text: str) -> str:
    return _c(text, "2")


def _bold(text: str) -> str:
    return _c(text, "1")


# ── Banner ────────────────────────────────────────────────────────────────
_BANNER_ART = r"""  ___                  ____                _                   _   _
 / _ \ _ __   ___ _ _ / ___|___  _ __  ___| |_ _ _ _   _  ___ | |_(_) ___  _ _
| | | | '_ \ / _ \ '_| |   / _ \| '_ \/ __| __| '_| | | |/ __|| __| |/ _ \| '_ \
| |_| | |_) |  __/ | | |__| (_) | | | \__ \ |_| |  | |_| | (__ | |_| | (_) | | | |
 \___/| .__/ \___|_|  \____\___/|_| |_|___/\__|_|   \__,_|\___(_)__|_|\___/|_| |_|
      |_|                                                             ERP"""


def print_startup_banner(
    version: str,
    host: str,
    port: int,
    data_dir: Path,
    *,
    serve_frontend: bool,
) -> None:
    """Print a friendly multi-line startup banner.

    Shown after the server has bound its socket and is ready to accept
    connections. Designed to be scanned in under three seconds: what URL
    to open, how to log in, where the data lives, how to stop.
    """
    url = f"http://{host}:{port}"
    print()
    print(_amber(_BANNER_ART))
    print()
    print(f"  {_bold('OpenConstructionERP')} {_dim('v' + version)}")
    print(f"  {_dim('Open-source construction cost estimation platform')}")
    print()
    print(f"  {_bold('Open in your browser:')}  {_amber(url)}")
    if serve_frontend:
        print(f"  {_dim('API docs:')}              {url}/api/docs")
    else:
        print(f"  {_dim('API only (frontend not bundled). Docs:')} {url}/api/docs")
    print()
    print(f"  {_bold('Demo login')} {_dim('(auto-created on first run)')}")
    print(f"    {_dim('Email:')}    demo@openestimator.io")
    print(f"    {_dim('Password:')} DemoPass1234!")
    print()
    print(f"  {_dim('Data directory:')} {data_dir}")
    print(f"  {_dim('Stop the server:')} Ctrl+C")
    print(f"  {_dim('Need help:')} {DOCS_URL}")
    print()


# ── Environment setup ─────────────────────────────────────────────────────
def _setup_env(data_dir: Path, host: str, port: int) -> None:
    """Configure environment variables for local-first operation.

    All settings use ``setdefault`` so the user can still override via
    a real environment variable or a .env file.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "vectors").mkdir(exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)

    db_path = data_dir / "openestimate.db"

    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{db_path}")
    os.environ.setdefault("VECTOR_BACKEND", "lancedb")
    os.environ.setdefault("VECTOR_DATA_DIR", str(data_dir / "vectors"))
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("APP_DEBUG", "false")
    os.environ.setdefault("ALLOWED_ORIGINS", f"http://{host}:{port}")
    os.environ.setdefault("JWT_SECRET", "openestimate-local-dev-key")

    # Desktop / CLI mode: serve frontend from the wheel
    os.environ["SERVE_FRONTEND"] = "true"

    # Publish the ready banner info so main.py can pick it up after the
    # uvicorn socket is actually bound (see core/startup_banner.py).
    os.environ["OE_CLI_HOST"] = host
    os.environ["OE_CLI_PORT"] = str(port)
    os.environ["OE_CLI_DATA_DIR"] = str(data_dir)


# ── Pre-flight checks ─────────────────────────────────────────────────────
class Check:
    """A single doctor check result."""

    def __init__(self, name: str, status: str, message: str, hint: str = "") -> None:
        self.name = name
        self.status = status  # "ok" | "warn" | "error"
        self.message = message
        self.hint = hint

    def print(self) -> None:
        badge = {
            "ok": _green("  OK   "),
            "warn": _yellow(" WARN  "),
            "error": _red(" ERROR "),
        }.get(self.status, self.status)
        print(f"  [{badge}] {self.name}: {self.message}")
        if self.hint and self.status != "ok":
            arrow = _u("\u2192 ", "-> ")
            print(f"            {_dim(arrow + self.hint)}")


def check_python_version() -> Check:
    ver = sys.version_info
    if (ver.major, ver.minor) < MIN_PYTHON:
        return Check(
            "Python version",
            "error",
            f"Python {ver.major}.{ver.minor} is too old (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)",
            f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ from python.org and reinstall the package",
        )
    return Check(
        "Python version",
        "ok",
        f"Python {ver.major}.{ver.minor}.{ver.micro}",
    )


def check_package_installed() -> Check:
    try:
        from importlib.metadata import version as _v

        v = _v("openconstructionerp")
        return Check("Package installed", "ok", f"openconstructionerp v{v}")
    except Exception:
        return Check(
            "Package installed",
            "warn",
            "running from source checkout (not pip-installed)",
            "For production use: pip install openconstructionerp",
        )


def check_data_dir(data_dir: Path) -> Check:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".writetest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("Data directory", "ok", f"writable at {data_dir}")
    except Exception as exc:
        return Check(
            "Data directory",
            "error",
            f"cannot write to {data_dir}: {exc}",
            f"Use --data-dir to pick a writable path, e.g. --data-dir {Path.home() / 'openestimate-data'}",
        )


def check_port_free(host: str, port: int) -> Check:
    """Verify nothing is already listening on the requested port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            # Linux/macOS: bind fails if port is in use.
            # Windows: connect succeeds if something is already listening.
            if sys.platform == "win32":
                try:
                    sock.connect((host, port))
                    # Connection succeeded → port is in use.
                    return Check(
                        "Port available",
                        "error",
                        f"port {port} on {host} is already in use",
                        f"Stop the other process or use --port {port + 1}",
                    )
                except (OSError, ConnectionRefusedError):
                    pass
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((host, port))
                except OSError as exc:
                    return Check(
                        "Port available",
                        "error",
                        f"port {port} on {host} is already in use ({exc})",
                        f"Stop the other process or use --port {port + 1}",
                    )
        return Check("Port available", "ok", f"port {port} is free")
    except Exception as exc:
        return Check("Port available", "warn", f"could not check port {port}: {exc}")


def check_frontend_bundled() -> Check:
    pkg_dir = Path(__file__).parent / "_frontend_dist"
    if pkg_dir.is_dir() and (pkg_dir / "index.html").exists():
        return Check("Frontend bundle", "ok", "bundled React UI ready")
    dev_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dev_dist.is_dir() and (dev_dist / "index.html").exists():
        return Check("Frontend bundle", "ok", f"using dev build from {dev_dist}")
    return Check(
        "Frontend bundle",
        "warn",
        "no frontend found — server will run API only",
        "Reinstall the pip package to get the bundled UI, or run `npm run build` in frontend/",
    )


def check_env_overrides() -> Check:
    """Warn if DATABASE_URL / JWT_SECRET look wrong."""
    db = os.environ.get("DATABASE_URL", "")
    if db and not (db.startswith("sqlite") or db.startswith("postgresql")):
        return Check(
            "DATABASE_URL",
            "warn",
            f"unrecognised scheme: {db.split(':', 1)[0]}",
            "Use sqlite+aiosqlite:///... or postgresql+asyncpg://...",
        )
    if db.startswith("postgresql"):
        return Check("DATABASE_URL", "ok", "PostgreSQL mode")
    return Check("DATABASE_URL", "ok", "SQLite mode (default)")


def check_core_tabular_deps() -> list[Check]:
    """Verify base tabular dependencies are importable.

    `pandas` and `pyarrow` were promoted from the `[vector]` extra into
    base dependencies in v1.3.13 after a fresh-install bug where the
    CWICR cost-database loader returned HTTP 500 with "No module named
    'pandas'". They are needed by:
      - the `load-cwicr` headline quickstart endpoint
      - the BIM Excel parser (openpyxl + pandas)
      - parquet seed data for classifications & cost databases

    A missing install here is a hard ERROR, not a warning — the app
    will boot but the first onboarding step will 500.
    """
    from importlib.util import find_spec

    hint = (
        "Cost database import requires pandas + pyarrow. "
        "Reinstall with: pip install --upgrade openconstructionerp"
    )
    out: list[Check] = []
    for mod in ("pandas", "pyarrow"):
        try:
            present = find_spec(mod) is not None
        except Exception:
            present = False
        if present:
            out.append(Check(f"Tabular core ({mod})", "ok", f"{mod} installed"))
        else:
            out.append(
                Check(
                    f"Tabular core ({mod})",
                    "error",
                    f"{mod} is missing from base dependencies",
                    hint,
                )
            )
    return out


def check_ai_provider_keys() -> Check:
    """Check whether at least one LLM provider API key is configured.

    We call LLM providers via REST (httpx), not vendor SDKs, so there is
    no Python package to probe. Instead, look at the two places keys can
    live:
      1. Settings / environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
      2. ``~/.openestimate/config.json`` (CLI-managed overrides)

    This only reports INFO-level WARN when none are set — AI is optional.
    """
    # 1. Settings-level keys (env vars, .env file, pydantic-settings).
    env_key_names = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
    )
    configured = [name for name in env_key_names if os.environ.get(name)]

    # 2. CLI config file overrides.
    config_path = DEFAULT_DATA_DIR / "config.json"
    if config_path.exists():
        try:
            import json

            with open(config_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            if isinstance(cfg, dict):
                for key, val in cfg.items():
                    if key.lower().endswith("_api_key") and val:
                        configured.append(key.upper())
        except Exception:
            pass

    if configured:
        names = ", ".join(sorted({c.split("_")[0].title() for c in configured}))
        return Check(
            "AI provider keys",
            "ok",
            f"configured: {names}",
        )
    return Check(
        "AI provider keys",
        "warn",
        "no LLM provider API key found (AI estimation will be disabled)",
        "Set e.g. ANTHROPIC_API_KEY or OPENAI_API_KEY, or configure via Settings > AI in the UI",
    )


def check_optional_extras() -> list[Check]:
    """Report which optional extras are installed (mostly non-fatal)."""
    from importlib.util import find_spec

    def _present(mod: str) -> bool:
        try:
            return find_spec(mod) is not None
        except Exception:
            return False

    out: list[Check] = []

    # Embedded vector search (LanceDB) — used by the local semantic search
    # path for cost-database matching. Optional: code falls back to keyword
    # match when missing.
    if _present("lancedb"):
        out.append(Check("Vector search [vector]", "ok", "lancedb installed"))
    else:
        out.append(
            Check(
                "Vector search [vector]",
                "warn",
                "not installed (LanceDB semantic search disabled)",
                "pip install 'openconstructionerp[vector]'",
            )
        )

    # Semantic embeddings (sentence-transformers + Qdrant client).
    # Renamed from `[ai]` in v1.3.14 — the old extra is still an alias.
    if _present("sentence_transformers"):
        out.append(
            Check("Semantic search [semantic]", "ok", "sentence-transformers installed")
        )
    else:
        out.append(
            Check(
                "Semantic search [semantic]",
                "warn",
                "not installed (RAG / embedding search disabled)",
                "pip install 'openconstructionerp[semantic]'",
            )
        )

    # PDF parsing for takeoff / document extraction.
    if _present("pymupdf") or _present("fitz"):
        out.append(Check("PDF takeoff [cv]", "ok", "pymupdf installed"))
    else:
        out.append(
            Check(
                "PDF takeoff [cv]",
                "warn",
                "not installed (PDF takeoff disabled)",
                "pip install 'openconstructionerp[cv]'",
            )
        )

    # AI provider key configuration (not a package check).
    out.append(check_ai_provider_keys())

    return out


def run_preflight(
    host: str,
    port: int,
    data_dir: Path,
    *,
    verbose: bool = True,
) -> list[Check]:
    """Run the core preflight checks and return the list."""
    checks: list[Check] = [
        check_python_version(),
        check_package_installed(),
        check_data_dir(data_dir),
        check_port_free(host, port),
        check_frontend_bundled(),
        check_env_overrides(),
    ]
    # Base tabular deps (pandas, pyarrow) are ERROR-level: the onboarding
    # load-cwicr endpoint hard-requires them. Run on every preflight so
    # `serve` also catches a broken install before uvicorn spins up.
    checks.extend(check_core_tabular_deps())
    if verbose:
        checks.extend(check_optional_extras())
    return checks


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_serve(args: argparse.Namespace) -> None:
    """Start the OpenConstructionERP server."""
    data_dir = Path(args.data_dir).expanduser().resolve()
    _setup_env(data_dir, args.host, args.port)

    # Run only the fatal preflight checks before attempting to start.
    # If a check fails hard, we stop here with a readable message instead
    # of letting uvicorn crash with a stack trace.
    fatal_checks = [
        check_python_version(),
        check_data_dir(data_dir),
        check_port_free(args.host, args.port),
        *check_core_tabular_deps(),
    ]
    blocking = [c for c in fatal_checks if c.status == "error"]
    if blocking:
        print(_red(_bold(_u("Cannot start OpenConstructionERP \u2014 pre-flight checks failed:",
                              "Cannot start OpenConstructionERP - pre-flight checks failed:"))))
        print()
        for c in fatal_checks:
            c.print()
        print()
        print(_dim("Run 'openestimate doctor' for full diagnostics."))
        print(_dim(f"Troubleshooting: {TROUBLESHOOTING_URL}"))
        sys.exit(1)

    try:
        from app.config import get_settings

        settings = get_settings()
        version = settings.app_version
    except Exception as exc:
        print(_red(f"Failed to load settings: {exc}"))
        print(_dim(f"Troubleshooting: {TROUBLESHOOTING_URL}"))
        sys.exit(1)

    # Print the banner BEFORE uvicorn starts so the user sees it immediately
    # even if module discovery takes a few seconds.
    if not args.quiet:
        print_startup_banner(
            version=version,
            host=args.host,
            port=args.port,
            data_dir=data_dir,
            serve_frontend=True,
        )
        print(_dim(_u("  Starting server… first run may take up to 30 seconds.",
                       "  Starting server... first run may take up to 30 seconds.")))
        print()

    if args.open:
        import threading
        import time

        def _open_browser() -> None:
            time.sleep(3)
            try:
                webbrowser.open(f"http://{args.host}:{args.port}")
            except Exception:
                pass

        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        import uvicorn

        uvicorn.run(
            "app.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            log_level="warning" if args.quiet else "info",
            access_log=False,
        )
    except KeyboardInterrupt:
        print()
        print(_dim("Server stopped. Bye!"))
    except OSError as exc:
        print()
        print(_red(_bold("Server failed to start:")) + f" {exc}")
        arrow = _u("\u2192", "->")
        if "address already in use" in str(exc).lower() or "10048" in str(exc):
            print(
                _dim(f"  {arrow} Port {args.port} is already in use. Try: openestimate serve --port {args.port + 1}")
            )
        else:
            print(_dim(f"  {arrow} See: {TROUBLESHOOTING_URL}"))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        arrow = _u("\u2192", "->")
        print()
        print(_red(_bold("Unexpected startup error:")) + f" {type(exc).__name__}: {exc}")
        print(_dim(f"  {arrow} Run 'openestimate doctor' to diagnose."))
        print(_dim(f"  {arrow} Report this at: {ISSUES_URL}"))
        sys.exit(1)


def cmd_init_db(args: argparse.Namespace) -> None:
    """Initialise data directory and create the SQLite database."""
    data_dir = Path(args.data_dir).expanduser().resolve()
    print(_u("Initialising data directory at ", "Initialising data directory at ")
          + f"{_bold(str(data_dir))}"
          + _u("…", "..."))
    _setup_env(data_dir, DEFAULT_HOST, DEFAULT_PORT)

    # Trigger the same SQLite auto-migration that main.py does on startup,
    # so `init-db` actually creates the tables and the first `serve` starts
    # instantly without table creation lag.
    import asyncio

    # Mirrors the list in main.py's startup hook — keep the two lists in
    # sync when adding a new module.
    _module_names = [
        "ai", "assemblies", "bim_hub", "boq", "catalog", "cde",
        "changeorders", "collaboration", "contacts", "correspondence",
        "costmodel", "costs", "documents", "enterprise_workflows",
        "erp_chat", "fieldreports", "finance", "full_evm",
        "i18n_foundation", "inspections", "integrations", "markups",
        "meetings", "ncr", "notifications", "procurement", "projects",
        "punchlist", "reporting", "requirements", "rfi", "rfq_bidding",
        "risk", "safety", "schedule", "submittals", "takeoff", "tasks",
        "teams", "tendering", "transmittals", "users", "validation",
    ]

    # Track import failures so we can report them loudly. Silently
    # swallowing these (as the pre-v1.3.14 code did) led to "no such
    # table" errors at runtime — the user saw "Ready." during init-db
    # and then the server 500'd on the first query to a missing model.
    failed_imports: list[tuple[str, str]] = []
    imported_ok = 0

    async def _create() -> None:
        nonlocal imported_ok
        import importlib

        from app.database import Base, engine

        for name in _module_names:
            try:
                importlib.import_module(f"app.modules.{name}.models")
                imported_ok += 1
            except ImportError as exc:
                failed_imports.append((name, f"ImportError: {exc}"))
                logger.warning("init-db: failed to import app.modules.%s.models: %s", name, exc)
            except Exception as exc:  # noqa: BLE001
                # Non-ImportError (e.g. syntax error, attribute error) is
                # still a real problem — record it.
                failed_imports.append((name, f"{type(exc).__name__}: {exc}"))
                logger.warning(
                    "init-db: %s while importing app.modules.%s.models: %s",
                    type(exc).__name__,
                    name,
                    exc,
                )

        try:
            from app.core.sqlite_migrator import sqlite_auto_migrate

            await sqlite_auto_migrate(engine, Base)
        except Exception as exc:  # noqa: BLE001
            logger.warning("init-db: sqlite_auto_migrate skipped: %s", exc)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    try:
        asyncio.run(_create())
    except Exception as exc:
        print(_red(f"Database initialisation failed: {exc}"))
        print(_dim(f"  {_u('\u2192', '->')} Run 'openestimate doctor' for diagnostics."))
        sys.exit(1)

    total = len(_module_names)
    print()
    print(f"  {_dim('Modules:')}  imported {imported_ok}/{total} module models")

    if failed_imports:
        print()
        print(_red(_bold(f"  {len(failed_imports)} module(s) failed to import:")))
        for name, err in failed_imports:
            print(f"    - {_bold(name)}: {_dim(err)}")
        print()
        print(
            _red(
                "Schema may be incomplete. Reinstall the package or check the error above."
            )
        )
        print(_dim(f"  {_u('\u2192', '->')} pip install --upgrade --force-reinstall openconstructionerp"))
        print(_dim(f"  {_u('\u2192', '->')} Then run 'openestimate doctor' to verify."))
        sys.exit(1)

    print()
    print(_green(_bold("Ready.")))
    print(f"  {_dim('Database:')} {data_dir / 'openestimate.db'}")
    print(f"  {_dim('Vectors:')}  {data_dir / 'vectors'}")
    print(f"  {_dim('Uploads:')}  {data_dir / 'uploads'}")
    print()
    print(f"Next: {_amber('openestimate serve')}")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run pre-flight checks and report OK / WARN / ERROR per item."""
    data_dir = Path(args.data_dir).expanduser().resolve()

    print()
    print(_bold(_u("OpenConstructionERP \u2014 doctor", "OpenConstructionERP - doctor")))
    print(_dim(f"Checking install at {data_dir}"))
    print()

    checks = run_preflight(args.host, args.port, data_dir, verbose=True)
    for c in checks:
        c.print()

    errors = [c for c in checks if c.status == "error"]
    warns = [c for c in checks if c.status == "warn"]

    print()
    if errors:
        print(_red(_bold(f"  {len(errors)} error(s)")) + _dim(f", {len(warns)} warning(s)"))
        print()
        print(_dim("Fix the errors above, then run 'openestimate serve'."))
        print(_dim(f"Docs: {TROUBLESHOOTING_URL}"))
        sys.exit(1)
    elif warns:
        print(_yellow(_bold(f"  {len(warns)} warning(s)")) + _dim(_u(" \u2014 non-fatal, server will run", " - non-fatal, server will run")))
        print()
        print(f"Run: {_amber('openestimate serve')}")
    else:
        print(_green(_bold("  All checks passed.")))
        print()
        print(f"Run: {_amber('openestimate serve')}")


def cmd_version(_args: argparse.Namespace) -> None:
    """Print version information."""
    try:
        from importlib.metadata import version as _v

        version = _v("openconstructionerp")
    except Exception:
        try:
            from app.config import Settings

            version = Settings.model_fields["app_version"].default
        except Exception:
            version = "unknown"

    print(f"OpenConstructionERP v{version}")
    print(f"Python {sys.version.split()[0]} ({sys.platform})")
    print(f"Docs: {DOCS_URL}")


def cmd_seed(args: argparse.Namespace) -> None:
    """Load demo data into the database."""
    data_dir = Path(args.data_dir).expanduser().resolve()
    _setup_env(data_dir, DEFAULT_HOST, DEFAULT_PORT)

    import asyncio

    async def _run_seed() -> None:
        from app.config import get_settings

        settings = get_settings()
        if "sqlite" in settings.database_url:
            from app.database import Base, engine
            from app.modules.boq import models as _  # noqa: F401
            from app.modules.costs import models as _  # noqa: F401
            from app.modules.projects import models as _  # noqa: F401
            from app.modules.users import models as _  # noqa: F401

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        print("Database tables created.")

        if args.demo:
            print(_u("Loading demo project data…", "Loading demo project data..."))
            from app.core.demo_projects import install_demo_project
            from app.database import async_session_factory

            async with async_session_factory() as session:
                result = await install_demo_project(session, "office_tower_berlin")
                await session.commit()
                print(f"Demo project installed: {result.get('project_name', 'OK')}")

        print("Seed complete.")

    asyncio.run(_run_seed())


# ── Arg parser ────────────────────────────────────────────────────────────
def _add_common_server_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="openestimate",
        description=(
            "OpenConstructionERP — open-source construction cost estimation platform.\n\n"
            "Quick start:\n"
            "    openestimate init-db\n"
            "    openestimate serve\n"
            "\n"
            "Then open http://localhost:8080 — log in with demo@openestimator.io / DemoPass1234!"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start the OpenConstructionERP server")
    _add_common_server_args(serve_p)
    serve_p.add_argument("--open", action="store_true", help="Open browser after startup")
    serve_p.add_argument("--quiet", action="store_true", help="Suppress banner and info logs")

    # init-db (canonical) + init (alias for backward compat)
    init_db_p = subparsers.add_parser(
        "init-db",
        help="Create the local SQLite database and data directories",
    )
    init_db_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    # Legacy alias — same args, same handler.
    init_p = subparsers.add_parser("init", help="Alias for init-db")
    init_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )

    # doctor
    doctor_p = subparsers.add_parser("doctor", help="Run installation health checks")
    _add_common_server_args(doctor_p)

    # version
    subparsers.add_parser("version", help="Show version information")

    # seed
    seed_p = subparsers.add_parser("seed", help="Load seed/demo data")
    seed_p.add_argument("--demo", action="store_true", help="Install demo project with sample data")
    seed_p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command in ("init-db", "init"):
        cmd_init_db(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "version":
        cmd_version(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command is None:
        # Default: serve with sensible defaults + open browser
        args.host = DEFAULT_HOST
        args.port = DEFAULT_PORT
        args.data_dir = str(DEFAULT_DATA_DIR)
        args.open = True
        args.quiet = False
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
