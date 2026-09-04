# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""OpenConstructionERP CLI - run the platform from the command line.

The happy path for a new user is two commands:

    pip install openconstructionerp
    openconstructionerp

The bare ``openconstructionerp`` command creates the local database,
loads the demo data, starts the server and opens the browser. The
explicit subcommands are still there for advanced use:

    openconstructionerp serve   [--host HOST] [--port PORT] [--data-dir DIR] [--open]
    openconstructionerp init-db [--data-dir DIR]
    openconstructionerp doctor  [--host HOST] [--port PORT] [--data-dir DIR]
    openconstructionerp seed    [--demo] [--data-dir DIR]
    openconstructionerp version

``openconstructionerp --version`` (or ``-V``) prints the same report as the
``version`` subcommand. It is the spelling most people reach for first, and it
used to exit 2 with an argparse error.

``openconstructionerp doctor`` runs pre-flight checks and prints OK /
WARNING / ERROR per check so you can diagnose install problems.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import socket
import sys
import webbrowser
from pathlib import Path

# ── Console encoding hardening ────────────────────────────────────────────
# On Windows + Anaconda Python the default console encoding is cp1252,
# which crashes on any non-ASCII character (em-dash, arrow, box-drawing,
# etc.). This is the same family of bug that killed v1.3.9 - silent or
# noisy failure on Windows. We try to switch stdout/stderr to UTF-8 if
# possible; otherwise we fall back to ASCII-only output.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── Re-execution by multiprocessing in a frozen build ─────────────────────
#
# In a PyInstaller build ``sys.executable`` is this binary, so when the
# standard library starts one of its own helper processes it re-executes us.
# Two different command lines arrive and they need different handling.
#
# ``multiprocessing.spawn.get_command_line`` has a ``sys.frozen`` branch, so a
# spawned child is started as ``<exe> --multiprocessing-fork ...`` and
# ``freeze_support()`` answers it. The resource tracker has no such branch:
# ``multiprocessing/resource_tracker.py`` builds ``[exe] +
# _args_from_interpreter_flags() + ['-c', code]`` unconditionally, so the
# frozen binary is handed a command line only an interpreter can answer.
#
# Measured on macos-latest in run 33834902654. The sidecar served the cold
# start, and then on a restart over its own data printed
#
#     openconstructionerp: error: argument command: invalid choice:
#     'from multiprocessing.resource_tracker import main;main(18)'
#
# and died with ``Abort trap: 6`` without ever answering /api/health. On a
# user's machine that is the launcher stopping at "Starting the application
# server" on the second launch, having worked on the first.
#
# ``freeze_support()`` on its own does not cover it, and this is the half that
# is easy to get wrong: ``spawn.is_forking`` returns True only for
# ``--multiprocessing-fork``, so the ``-c`` line above walks straight past it
# into argparse. Both guards are needed. Both are gated on ``sys.frozen``,
# because outside a frozen build the standard library re-executes the real
# interpreter it finds through ``sys._base_executable`` and never reaches us.
#
# What may precede ``-c`` is whatever ``subprocess._args_from_interpreter_flags``
# derives from the parent's ``sys.flags``: -O and -OO, repeats of -d -B -S -v
# -b and -q, -I -E -s -P, -W with its value attached, and -X with its value as
# a separate argument. A frozen build commonly runs with no_site, so testing
# ``argv[1] == "-c"`` would pass on a CI runner and fail on a user's machine.

_INTERPRETER_FLAG_LETTERS = frozenset("OdBSvbqIEsP")


def interpreter_code_argument(argv: list[str]) -> str | None:
    """Return the code of an interpreter-style ``-c`` invocation, else None.

    ``argv`` is the argument list with the program name already removed. The
    scan stops at the first argument that is not an interpreter flag, so an
    ordinary invocation such as ``serve --port 8741`` is declined and reaches
    the parser unchanged.
    """
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "-c":
            return argv[index + 1] if index + 1 < len(argv) else None
        if arg == "-X":
            index += 2
            continue
        if arg.startswith("-W") and len(arg) > 2:
            index += 1
            continue
        if len(arg) > 1 and arg[0] == "-" and set(arg[1:]) <= _INTERPRETER_FLAG_LETTERS:
            index += 1
            continue
        return None
    return None


def _answer_multiprocessing_re_execution() -> None:
    """Answer the command lines multiprocessing uses to start its helpers.

    Returns normally for an ordinary invocation. Does not return when the
    arguments belong to the standard library rather than to a user.
    """
    if not getattr(sys, "frozen", False):
        return

    import multiprocessing

    # Exits the process when the arguments are a spawned child's.
    multiprocessing.freeze_support()

    code = interpreter_code_argument(sys.argv[1:])
    if code is None:
        return
    # What an interpreter does with -c. This grants nobody anything new:
    # whoever can choose this process's arguments can already run whatever
    # they like in the shell they typed them into.
    exec(compile(code, "<multiprocessing>", "exec"), {"__name__": "__main__"})
    raise SystemExit(0)


def _stdout_supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def _default_data_dir() -> Path:
    """Where the CLI keeps its data when nothing on the command line says otherwise.

    Everything else in the platform that resolves a data directory honours the
    same three overrides in the same order: ``OE_DATA_DIR``, then ``DATA_DIR``,
    then ``OE_CLI_DATA_DIR``. The uploads root does, the JWT secret does, the
    demo seed does, the partner pack state does. This one did not, and the
    result was a split: an operator who set ``OE_DATA_DIR`` to a mounted volume
    got their uploads and their signing secret on the volume and their database,
    their cluster and their config file left behind in the home directory, which
    on a container is the layer that disappears on redeploy. The override was
    documented and half honoured, which is worse than not honouring it, because
    nothing reports the half that was ignored.

    An explicit ``--data-dir`` still wins: this only supplies the default.
    """
    override = os.environ.get("OE_DATA_DIR") or os.environ.get("DATA_DIR") or os.environ.get("OE_CLI_DATA_DIR")
    if override and override.strip():
        return Path(override.strip())
    try:
        return Path.home() / ".openestimate"
    except RuntimeError:
        # No home directory can be resolved (a minimal container with HOME
        # unset and no passwd entry). A relative path beats aborting the CLI.
        return Path(".openestimate")


DEFAULT_DATA_DIR = _default_data_dir()
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MIN_PYTHON = (3, 12)

DOCS_URL = "https://openconstructionerp.com/docs"
TROUBLESHOOTING_URL = "https://openconstructionerp.com/docs#troubleshooting"
ISSUES_URL = "https://github.com/datadrivenconstruction/OpenConstructionERP/issues"
COMMUNITY_URL = "https://t.me/datadrivenconstruction"
GITHUB_URL = "https://github.com/datadrivenconstruction/OpenConstructionERP"

logger = logging.getLogger("openestimate.cli")


# ── Data directory: declared once, resolved once ──────────────────────────
# Every command that works in the data directory goes through these two
# functions. Spelling the flag out per command, and resolving it per command,
# is how a path ends up anchored on the working directory: the command that
# forgets is invisible next to the four that remembered, and on a development
# box or in CI the working directory is writable, so nothing reports it. It
# only surfaces on an install under a directory the process may not write to.
# One declaration and one resolution mean a command added later either uses
# them or has no data directory at all, and the unit test named after this
# section fails the build if a second spelling of either one appears.
def _add_data_dir_arg(p: argparse.ArgumentParser) -> None:
    """Declare ``--data-dir`` on a subcommand parser.

    Args:
        p: The subcommand parser that should accept a data directory.
    """
    p.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )


def _data_dir_from_args(args: argparse.Namespace) -> Path:
    """Resolve the data directory this invocation works in.

    Absolute either way: an explicit ``--data-dir`` is expanded and resolved,
    and a command that declares no such flag falls back to
    :data:`DEFAULT_DATA_DIR`, which already honours ``OE_DATA_DIR`` /
    ``DATA_DIR`` / ``OE_CLI_DATA_DIR``. Nothing here is left relative to the
    working directory.

    A blank value is how a compose file and a launcher script spell "not set",
    and ``Path("")`` is the working directory, so blanks fall back to the
    default exactly as they do in :func:`_default_data_dir`.

    Args:
        args: The parsed command line.

    Returns:
        An absolute path to the data directory.
    """
    raw = getattr(args, "data_dir", None)
    value = str(raw).strip() if raw is not None else ""
    base = Path(value) if value else DEFAULT_DATA_DIR
    return base.expanduser().resolve()


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


def _bar() -> str:
    """Left accent rule for the info panels (amber bar, ASCII pipe fallback)."""
    return _amber(_u("┃", "|"))


# ── Banner ────────────────────────────────────────────────────────────────
# "OpenConstructionERP" rendered in the figlet "small" font (82 cols × 5
# rows). The previous "Standard" font wrapped the 19-character name onto
# multiple visual rows on a typical 80-col terminal, which looked crooked;
# the "small" font fits the full name on one row with the trailing "ERP"
# inline. Generated once with pyfiglet and pasted in - no runtime dep.
_BANNER_ART = r"""  ___                 ___             _               _   _          ___ ___ ___
 / _ \ _ __  ___ _ _ / __|___ _ _  __| |_ _ _ _  _ __| |_(_)___ _ _ | __| _ \ _ \
| (_) | '_ \/ -_) ' \ (__/ _ \ ' \(_-<  _| '_| || / _|  _| / _ \ ' \| _||   /  _/
 \___/| .__/\___|_||_\___\___/_||_/__/\__|_|  \_,_\__|\__|_\___/_||_|___|_|_\_|
      |_|"""


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
    bar = _bar()
    check = _green(_u("✔", "OK"))
    print()
    print(_amber(_BANNER_ART))
    print()
    print(f"  {bar}  {check} {_bold('OpenConstructionERP is running')}  {_dim('v' + version)}")
    print(f"  {bar}")
    print(f"  {bar}  {_bold('Open in your browser')}")
    print(f"  {bar}     {_amber(url)}")
    if serve_frontend:
        print(f"  {bar}     {_dim(url + '/api/docs   (API reference)')}")
    else:
        print(f"  {bar}     {_dim('frontend not bundled, API only at ' + url + '/api/docs')}")
    print(f"  {bar}")
    print(f"  {bar}  {_bold('Log in with the demo account')}")
    print(f"  {bar}     demo@openconstructionerp.com  {_dim('/')}  DemoPass1234!")
    print(f"  {bar}")
    print(f"  {bar}  {_dim('Stop'.ljust(11))} Ctrl+C")
    print(f"  {bar}  {_dim('Start again'.ljust(11))} {_amber('openconstructionerp')}")
    print(
        f"  {bar}  {_dim('or, anywhere'.ljust(11))} {_amber('python -m openconstructionerp')}  {_dim('(works without PATH)')}"
    )
    print(f"  {bar}  {_dim('Data folder'.ljust(11))} {data_dir}")
    print(f"  {bar}  {_dim('Need help'.ljust(11))} {DOCS_URL}")
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

    # Embedded PostgreSQL (no Docker) is the DEFAULT runtime: boot a real
    # in-process PG16 and point DATABASE_URL/DATABASE_SYNC_URL at it. There is no
    # SQLite fallback - if the cluster cannot start we exit with an actionable
    # message. The operator opts out by supplying an external DATABASE_URL (then
    # is_requested() returns False and boot is skipped). Must run before any
    # ``from app...`` import that builds the engine - _setup_env is that earliest
    # point for every command.
    from app.core import embedded_pg

    if embedded_pg.is_requested():
        if embedded_pg.boot(data_dir):
            # The embedded cluster is up; the schema bring-up (create_all +
            # alembic) runs next, during app startup. Mark it so the desktop
            # launcher can show a "preparing database" step.
            embedded_pg.emit_stage("migrate", "start", "Preparing the database")
            # Transparent one-time SQLite -> PostgreSQL migration: if the box has
            # a legacy openestimate.db and the embedded cluster is still empty,
            # move the data over before the server starts. No-op otherwise.
            status = embedded_pg.auto_migrate_legacy_sqlite(data_dir)
            if status.startswith("migrated"):
                print(_green(_u("✓ ", "OK ")) + status)
            print(_green(_u("✓ ", "OK ")) + "Database: embedded PostgreSQL 16 (no Docker)")
        elif embedded_pg.last_fatal_detail():
            # boot() named the cause. The generic advice below would be actively
            # wrong for those: a data directory written by another PostgreSQL
            # major is not repaired by reinstalling, and reinstalling is how it
            # got there. Print what boot worked out instead of talking over it.
            print(_red(_u("✗ ", "X ")) + str(embedded_pg.last_fatal_detail()))
            raise SystemExit(1)
        else:
            # pixeltable-pgserver missing or initdb failed. There is no SQLite
            # fallback anymore: PostgreSQL is required, so fail loudly with an
            # actionable message instead of limping along on a different engine.
            print(
                _red(_u("✗ ", "X "))
                + "Embedded PostgreSQL could not start (already retried a few times). "
                + _repair_hint(
                    "Reinstall the package (pip install --upgrade --force-reinstall openconstructionerp), ",
                    "Reinstall the app from its installer, ",
                )
                + "run 'openconstructionerp doctor' for details, or "
                + "set DATABASE_URL to an external PostgreSQL."
            )
            print(
                _dim(
                    "  The underlying error is in the log at "
                    + str(data_dir / "pgdata" / "log")
                    + " (and "
                    + str(Path.home() / ".openestimate" / "desktop-launcher.log")
                    + "). If it keeps happening, send those logs to info@datadrivenconstruction.io."
                )
            )
            raise SystemExit(1)

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


def _repair_hint(pip_advice: str, frozen_advice: str | None = None) -> str:
    """Advice for a reader whose install shipped this and shipped it broken.

    Imported where it is used rather than at module scope, because ``doctor``
    is meant to answer quickly and the CLI already defers its app imports.

    Only one hint below can reach a desktop reader today, the [cv] one:
    everything else the doctor names is in ``requirements-desktop.lock``, so
    those branches report ok and never render a hint at all. That is a fact
    about today's lock rather than about this code. The day a dependency
    leaves the lock, or a check lands for something the bundle does not carry,
    another armed line goes live with nothing to catch it, which is why every
    site is routed rather than the one that is wrong now.

    ``frozen_advice`` is for the two sites that print mid-sentence, where the
    full paragraph would not fit the line being built.
    """
    from app.core.self_upgrade import DESKTOP_REPAIR, repair_hint

    return repair_hint(pip_advice, DESKTOP_REPAIR if frozen_advice is None else frozen_advice)


def _no_extra_hint(pip_advice: str) -> str:
    """Advice for a reader whose install never carried this in the first place.

    Separate from :func:`_repair_hint` because "reinstall" is not an answer
    here. A bundle reinstalled from the same installer carries exactly the same
    fixed set of packages, so that advice sends the reader round a loop while
    the check goes on printing the same line.
    """
    from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint

    return repair_hint(pip_advice, DESKTOP_NO_EXTRA)


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
            # A bundle that cannot read its own version is not a source
            # checkout and has nothing to install itself from.
            _repair_hint("For production use: pip install openconstructionerp"),
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
            f"Use --data-dir to pick a writable path, e.g. --data-dir {Path.home() / 'openconstructionerp-data'}",
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
    """Report the UI the server would actually serve, by asking the server's own lookup.

    This used to repeat ``Path(__file__).parent / "_frontend_dist"``, the same
    expression ``cli_static.get_frontend_dir()`` uses, on the reasoning that two
    copies of one expression cannot disagree. They can, and in the frozen
    desktop build they do, because the expression is identical and the anchor is
    not. This module is the PyInstaller entry script, so it is executed as
    ``__main__`` and its ``__file__`` sits at the root of the unpacked bundle;
    ``cli_static`` is an ordinary module inside the ``app`` package, so its
    ``__file__`` sits one level down, which is where the UI is actually
    unpacked. The copy here therefore looked one directory too high and
    reported "no frontend" on a sidecar that was serving the UI perfectly - a
    false negative on the desktop channel, where this check matters most,
    telling the operator to reinstall a package that was not broken.

    Asking the real lookup removes the duplication and the divergence together.
    A check that answers from its own reimplementation of the thing it is
    checking can only ever be right by coincidence.
    """
    try:
        # Imported inside the try, not above it. cli_static pulls fastapi and
        # starlette at module level, and this module's own imports are stdlib
        # only on purpose: that is what lets the CLI diagnose an install whose
        # dependencies did not resolve. run_preflight builds its list with no
        # per-check guard, so an ImportError escaping here would not degrade one
        # line, it would abort the whole report - on exactly the broken install
        # the report exists to explain.
        #
        # That guard is covered by unit tests and deliberately not by a frozen
        # build: fastapi and starlette are collected into the bundle alongside
        # everything else, so this import resolves there by construction. Making
        # it fail would mean excluding fastapi from the spec, and the resulting
        # sidecar would not start at all - measuring a build nobody could ship
        # rather than the guard working. The anchor question above is the
        # opposite case and was settled on a real artefact, which reported the
        # UI at <bundle>/app/_frontend_dist.
        #
        # One change would make a frozen test worth its cost: if cli_static ever
        # gains a conditional module-level import (a platform-gated or optional
        # dependency at the top of that file), then this import can fail inside
        # a healthy bundle and the frozen path stops being unreachable.
        from app.cli_static import get_frontend_dir

        return Check("Frontend bundle", "ok", f"bundled React UI ready at {get_frontend_dir()}")
    except FileNotFoundError:
        return Check(
            "Frontend bundle",
            "warn",
            "no frontend found - server will run API only",
            # `npm run build` is not an answer inside a bundle either: there is
            # no repo checkout beside it to run that in.
            _repair_hint("Reinstall the pip package to get the bundled UI, or run `npm run build` in frontend/"),
        )
    except Exception as exc:
        # Deliberately broad, because this function is a reporter: anything it
        # fails to catch it converts into the absence of every other check. A
        # lookup that cannot run is still its own finding, and not the same
        # finding as a UI that is absent.
        return Check(
            "Frontend bundle",
            "error",
            f"the frontend lookup could not run: {type(exc).__name__}: {exc}",
            _repair_hint("Reinstall the pip package: this install cannot load its own web stack."),
        )


def check_locales_bundled() -> Check:
    """Report the translation catalogue the server would actually load.

    Asks ``load_translations`` instead of testing the directory, for the reason
    spelled out on :func:`check_frontend_bundled` above: a check that
    reimplements the lookup it is checking is right only by coincidence. Here
    the lookup is a single line, which is what makes copying it tempting and
    what makes copying it wrong, because the path resolves to a directory NEXT
    TO the app package and therefore lands somewhere different in a source
    tree, a wheel and a frozen bundle.

    This is the twin of the frontend check and should always have existed
    beside it. Both are force-included into the wheel precisely because the
    package walk cannot see them, which makes them the two files most likely to
    be missing from a build; one of them had a preflight line and the other did
    not. The desktop sidecar shipped without the catalogue for the whole life of
    the desktop build and nothing said so, because the loader used to refill the
    directory from an embedded copy carrying 20 of the languages and a much
    smaller key set. The only symptom was a catalogue quietly missing most of
    its strings, which no check could see: every file present, parsing, and
    agreeing with the others.

    Error rather than warning, because the server treats it as one. When the
    catalogue is absent ``load_translations`` raises, startup aborts, and a
    desktop user is told only that the backend did not start in time. The point
    of this line is to say the true sentence before the server has to.
    """
    try:
        from app.core.i18n import get_available_locales, load_translations

        load_translations()
        locales = get_available_locales()
        loaded = [entry for entry in locales if entry["loaded"]]
    except FileNotFoundError as exc:
        return Check(
            "Translation catalogue",
            "error",
            f"missing: {exc}",
            _repair_hint(
                "Reinstall the pip package. If this is the desktop app, the build itself was "
                "assembled without the catalogue and only a corrected build fixes it: the bundle "
                "unpacks itself into a fresh temporary directory on every launch, so there is "
                "nowhere to put the files back."
            ),
        )
    except Exception as exc:
        # Broad on purpose, exactly as the frontend check above is: this
        # function is a reporter, and an exception escaping it would replace
        # every other line of the report with a traceback.
        return Check(
            "Translation catalogue",
            "error",
            f"the catalogue could not be loaded: {type(exc).__name__}: {exc}",
            _repair_hint("Reinstall the pip package: this install cannot load its own translations."),
        )

    if not loaded:
        return Check(
            "Translation catalogue",
            "error",
            "the directory is there and no locale in it could be read",
            _repair_hint("Reinstall the pip package: the translation files are unreadable or empty."),
        )
    if len(loaded) < len(locales):
        missing = ", ".join(sorted(str(entry["code"]) for entry in locales if not entry["loaded"]))
        return Check(
            "Translation catalogue",
            "warn",
            f"{len(loaded)} of {len(locales)} locales loaded, absent: {missing}",
            _repair_hint("Reinstall the pip package to get the whole catalogue."),
        )
    # "all N loaded" on its own reads as full language coverage and is not.
    # This catalogue holds the strings the SERVER writes, and it is a different
    # and shorter list than the languages the UI offers: 28 against 41 at the
    # time of writing, with nine of the offered languages having no file here
    # at all and reading English for anything the server produces. Counting
    # them here would mean the backend reading a frontend source file, which it
    # does nowhere else, so this says what it is counting instead and leaves
    # the comparison to the guard that owns it.
    return Check("Translation catalogue", "ok", f"all {len(loaded)} server-side locales loaded")


def check_env_overrides() -> Check:
    """Warn if DATABASE_URL / JWT_SECRET look wrong."""
    db = os.environ.get("DATABASE_URL", "")
    if db and not db.startswith("postgresql"):
        return Check(
            "DATABASE_URL",
            "warn",
            f"unsupported scheme: {db.split(':', 1)[0]}",
            "OpenConstructionERP runs only on PostgreSQL. Use postgresql+asyncpg://... "
            "or leave DATABASE_URL unset to use the embedded PostgreSQL.",
        )
    if db.startswith("postgresql"):
        return Check("DATABASE_URL", "ok", "external PostgreSQL")
    return Check("DATABASE_URL", "ok", "embedded PostgreSQL (default)")


def check_core_tabular_deps() -> list[Check]:
    """Verify base tabular dependencies are importable.

    `pandas` and `pyarrow` were promoted from the `[vector]` extra into
    base dependencies in v1.3.13 after a fresh-install bug where the
    CWICR cost-database loader returned HTTP 500 with "No module named
    'pandas'". They are needed by:
      - the `load-cwicr` headline quickstart endpoint
      - the BIM Excel parser (openpyxl + pandas)
      - parquet seed data for classifications & cost databases

    A missing install here is a hard ERROR, not a warning - the app
    will boot but the first onboarding step will 500.
    """
    from importlib.util import find_spec

    # Both are base dependencies, so a bundle missing one is damaged rather than
    # merely lean, and repair is the honest advice there.
    hint = _repair_hint(
        "Cost database import requires pandas + pyarrow. Reinstall with: pip install --upgrade openconstructionerp"
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


def check_ai_provider_keys(data_dir: Path | None = None) -> Check:
    """Check whether at least one LLM provider API key is configured.

    We call LLM providers via REST (httpx), not vendor SDKs, so there is
    no Python package to probe. Instead, look at the two places keys can
    live:
      1. Settings / environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
      2. ``<data-dir>/config.json`` (CLI-managed overrides)

    This only reports INFO-level WARN when none are set - AI is optional.

    Args:
        data_dir: The data directory this invocation works in. This check read
            :data:`DEFAULT_DATA_DIR` instead, so ``doctor --data-dir`` reported
            on a config file belonging to a different installation while its
            sibling check on the same run reported on the directory it was
            given. Omitting it keeps the old default for a caller with no data
            directory in hand.
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
    config_path = (data_dir or DEFAULT_DATA_DIR) / "config.json"
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


def _pdf_reader_imports_in_process() -> bool:
    """Whether the PDF upload path imports its readers in this process.

    Mirrors ``app.modules.takeoff.service._use_in_process_pdf_parser``. It is
    restated here rather than imported because ``doctor`` has to stay runnable
    on an install too broken to import the takeoff service, which drags in the
    ORM and the whole app package. ``test_cli_doctor_pdf_probe`` asserts the
    two predicates agree, so they cannot drift apart unnoticed.
    """
    if getattr(sys, "frozen", False):
        return True
    return os.environ.get("OE_DESKTOP", "").strip().lower() in {"1", "true", "yes", "on"}


def check_optional_extras(data_dir: Path | None = None) -> list[Check]:
    """Report which optional extras are installed (mostly non-fatal).

    Args:
        data_dir: The data directory this invocation works in, forwarded to the
            checks that read a file out of it.
    """
    from importlib.util import find_spec

    def _present(mod: str) -> bool:
        try:
            return find_spec(mod) is not None
        except Exception:
            return False

    def _import_error(mod: str) -> str | None:
        """Import ``mod`` the same way the code that needs it will import it.

        Returns None when the import succeeds, otherwise the last line of the
        failure. Normally a child process is used, for two reasons: it is where
        the upload path imports its PDF readers, so this reproduces the real
        conditions; and a native extension that segfaults on load takes the
        child down instead of the diagnostic that was sent to find it.

        The frozen desktop build is the exception. There ``sys.executable`` is
        the app binary, not an interpreter, so ``-c`` is never honoured - which
        is exactly why the upload path parses in-process on desktop. Probing
        with a child there would report every healthy desktop install as a
        broken PDF reader, so the check follows the parser and imports in this
        process instead. The helper is named for the PDF readers because they
        were the first caller, but both reasons hold for any module with a
        native extension, which is why the vector and encoder checks below use
        it too.
        """
        import subprocess

        if _pdf_reader_imports_in_process():
            try:
                importlib.import_module(mod)
            except BaseException as exc:  # a bad native extension may SystemExit
                return f"{type(exc).__name__}: {exc}"[:200]
            return None

        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"import {mod}"],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except Exception as exc:  # could not even launch the child
            return f"{type(exc).__name__}: {exc}"[:200]
        if proc.returncode == 0:
            return None
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        last = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        return last[:200]

    def _extra_check(label: str, mod: str, extra: str, ok_msg: str, missing_msg: str) -> Check:
        """Report an optional extra as one of three states rather than two.

        ``find_spec`` answers "is it on disk", which is the wrong question for a
        module that is mostly a compiled extension. lancedb is almost entirely
        one Rust library and sentence-transformers imports torch, a pile of
        native shared objects, so either can resolve perfectly and still fail to
        load. Calling that "installed" is precisely the class of lie this
        command exists to catch, and it is not hypothetical: a frozen build was
        measured reporting the encoder as installed while carrying 167
        sentence-transformers modules and no torch whatsoever.

        Absent stays a warning, because a stock server is meant not to carry
        these. Present but unimportable is an error, because something did ship
        it and it does not work, and the operator needs to know those are
        different problems with different fixes. The cheap lookup runs first, so
        the import cost is only paid when there is something to prove: on the
        common install that simply lacks the extra, this costs what it did
        before.
        """
        if not _present(mod):
            return Check(
                label,
                "warn",
                missing_msg,
                _no_extra_hint(f"pip install 'openconstructionerp[{extra}]'"),
            )
        err = _import_error(mod)
        if err is None:
            return Check(label, "ok", ok_msg)
        return Check(
            label,
            "error",
            f"present but will not import: {err}",
            _repair_hint(f"pip install --force-reinstall 'openconstructionerp[{extra}]'"),
        )

    out: list[Check] = []

    # Embedded vector search (LanceDB) - used by the local semantic search
    # path for cost-database matching. Optional: code falls back to keyword
    # match when missing.
    out.append(
        _extra_check(
            "Vector search [vector]",
            "lancedb",
            "vector",
            "lancedb imports cleanly",
            "not installed (LanceDB semantic search disabled)",
        )
    )

    # Semantic embeddings (sentence-transformers + Qdrant client).
    # Renamed from `[ai]` in v1.3.14 - the old extra is still an alias.
    out.append(
        _extra_check(
            "Semantic search [semantic]",
            "sentence_transformers",
            "semantic",
            "sentence-transformers imports cleanly",
            "not installed (RAG / embedding search disabled)",
        )
    )

    # PDF takeoff. This one is checked by importing, not by locating: find_spec
    # resolves a module without executing it, so a wheel whose native extension
    # will not load passes the lookup and then fails every upload - which is
    # exactly the "the check says the dependency is installed but uploads still
    # fail" report this check exists to prevent. The import runs in a child of
    # the same interpreter, which is where the upload path parses PDFs too, so
    # a reader that is broken only there is still caught and a reader that
    # crashes on import does not take the diagnostic down with it.
    #
    # pdfplumber is checked first because it is the reader the upload path
    # tries first; PyMuPDF is the fallback. Checking only the fallback was the
    # second half of the same blind spot.
    pdf_readers = [("pdfplumber", "primary reader"), ("pymupdf", "fallback reader")]
    pdf_failures = [(mod, role, err) for mod, role in pdf_readers if (err := _import_error(mod)) is not None]
    if not pdf_failures:
        out.append(Check("PDF takeoff", "ok", "pdfplumber + pymupdf import cleanly"))
    else:
        broken = "; ".join(f"{mod} ({role}): {err}" for mod, role, err in pdf_failures)
        # Losing only the fallback still leaves uploads working, so it is not
        # the same severity as losing the reader every upload starts with.
        both_gone = len(pdf_failures) == len(pdf_readers)
        out.append(
            Check(
                "PDF takeoff",
                "error" if both_gone else "warn",
                f"PDF reader will not import: {broken}",
                _repair_hint("pip install --force-reinstall --no-cache-dir openconstructionerp"),
            )
        )

    # Routed through the same helper as the other extras, which changes two
    # things. It reports when OCR is available instead of only when it is
    # absent: the old branch appended nothing at all on an install that had the
    # extra, so "OCR works here" and "this check never ran" printed identically,
    # which is the one thing a diagnostic must never do. And it verifies by
    # importing rather than by locating, so a wheel set that is present but
    # cannot load is reported as broken instead of as installed - the blind spot
    # this function's own docstring was written about, which had been closed for
    # the vector and encoder checks and left open one extra over.
    #
    # The engine is asked about separately, because importing the frontend does
    # not answer for it. [cv] resolves paddleocr and paddlex and does NOT pull
    # paddlepaddle: upstream expects the caller to choose a CPU, GPU or
    # platform-specific build. Measured on a throwaway venv carrying nothing but
    # `paddleocr==3.7.0`, exactly as the extra declares it: `import paddleocr`
    # succeeds, `from paddleocr import PaddleOCR` succeeds, and no engine is
    # installed. So find_spec says installed, a real import says installed, and
    # OCR still cannot run. Importing harder cannot separate these, which is why
    # the question changes rather than the depth of the probe.
    #
    # It gets its own line and its own severity because the fix is different. A
    # broken paddleocr is reinstalled; a missing engine is chosen and installed
    # per platform, and telling someone to reinstall the extra there sends them
    # round a loop that reproduces the same state.
    #
    # What is NOT covered: the failure at construction time. PaddleOCR() fetches
    # models over the network on first use, so probing it would measure the
    # operator's connection as much as their install, and no preflight check can
    # honestly do that.
    def _engine_distribution_installed() -> bool:
        """Is anything named like a paddlepaddle build installed?

        Asked by distribution name rather than by import name, and asked only
        as a second opinion. The engine imports as ``paddle`` but ships as
        ``paddlepaddle``, and the GPU build is a third name again, so neither
        question is safely sufficient alone: the import name would call a
        working install broken the day upstream renames it, and the
        distribution name alone misses an engine vendored some other way.

        Absence has to fail BOTH before it is reported, because a false
        "engine missing" is the worst result this check can produce. It tells
        an operator to install what they already have, and a check that cries
        wolf once is the check nobody reads the next time.

        A source-install instrument, not a frozen one: a PyInstaller bundle
        carries dist-info only for what its spec ran ``copy_metadata`` on, so
        this question answers "no" inside the desktop build regardless of what
        is bundled. That costs nothing today, because the lock carries no
        paddle at all and the first branch answers long before this one. It
        stops being free the day OCR ships to desktop.
        """
        try:
            from importlib.metadata import distributions

            found = distributions()
        except Exception:
            # A metadata directory that cannot even be listed must not take the
            # diagnostic down. It costs only the second opinion, which the
            # caller then reads as "not found here".
            return False

        for dist in found:
            # Guarded per entry, never per sweep. One unreadable dist-info
            # anywhere in site-packages would otherwise raise mid-iteration and
            # throw away the answer for every OTHER distribution, printing the
            # false "engine missing" this whole helper exists to prevent - and
            # doing it by iteration order, since a short-circuiting scan says
            # yes or no depending on whether the engine was reached before the
            # broken entry or after it.
            try:
                name = (dist.metadata["Name"] or "").lower()
            except Exception:
                continue
            if name.startswith("paddlepaddle"):
                return True
        return False

    cv_label = "PDF dimension OCR [cv]"
    if not _present("paddleocr"):
        out.append(
            Check(
                cv_label,
                "warn",
                "not installed (geometry detection still works; dimension-text reading disabled)",
                _no_extra_hint("pip install 'openconstructionerp[cv]'"),
            )
        )
    elif (cv_err := _import_error("paddleocr")) is not None:
        out.append(
            Check(
                cv_label,
                "error",
                f"present but will not import: {cv_err}",
                _repair_hint("pip install --force-reinstall 'openconstructionerp[cv]'"),
            )
        )
    elif not _present("paddle") and not _engine_distribution_installed():
        out.append(
            Check(
                cv_label,
                "error",
                "paddleocr is installed but its inference engine (paddlepaddle) is not - "
                "OCR will fail when a scanned drawing is uploaded, not here",
                # Routed too, though it never says "pip": what makes a remedy
                # unreachable is that it asks the reader to install something,
                # not the word it uses to ask. Testing only for the word would
                # have passed this line and left it broken.
                _no_extra_hint(
                    "Install a paddlepaddle build for this platform. The [cv] extra deliberately "
                    "does not choose one, because the right build depends on CPU vs GPU and OS."
                ),
            )
        )
    # find_spec is the gate here and the import is the verdict, deliberately in
    # that order and not to be collapsed into one. The lookup is cheap and only
    # decides whether there is anything to verify; the import is what decides
    # whether it works, which is the whole reason this function stopped trusting
    # find_spec. The verdict is also only pronounced when the import NAME
    # resolved: an engine found solely by its distribution name is left alone
    # rather than imported under a name it may not answer to, since guessing
    # wrong there would print "installed but will not import" at an install that
    # is fine.
    elif _present("paddle") and (engine_err := _import_error("paddle")) is not None:
        out.append(
            Check(
                cv_label,
                "error",
                f"the OCR engine is installed but will not import: {engine_err}",
                _repair_hint("Reinstall a paddlepaddle build matching this platform and Python version."),
            )
        )
    else:
        out.append(Check(cv_label, "ok", "paddleocr imports cleanly and a paddlepaddle engine is installed"))

    # AI provider key configuration (not a package check).
    out.append(check_ai_provider_keys(data_dir))

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
        check_locales_bundled(),
        check_env_overrides(),
    ]
    # Base tabular deps (pandas, pyarrow) are ERROR-level: the onboarding
    # load-cwicr endpoint hard-requires them. Run on every preflight so
    # `serve` also catches a broken install before uvicorn spins up.
    checks.extend(check_core_tabular_deps())
    if verbose:
        checks.extend(check_optional_extras(data_dir))
    return checks


# ── Commands ──────────────────────────────────────────────────────────────
def _run_fatal_preflight(data_dir: Path, host: str, port: int) -> None:
    """Run the blocking pre-flight checks, or exit 1 with a readable report.

    Only the checks that are cheap and that can be answered without any of the
    runtime environment ``_setup_env`` builds. Keeping the set to that is what
    lets the caller run it first; see the note at the call site for why running
    it first matters.

    Args:
        data_dir: The resolved data directory the server would use.
        host: Interface the server would bind.
        port: Port the server would bind.

    Raises:
        SystemExit: With code 1 when any check reports ``error``.
    """
    fatal_checks = [
        check_python_version(),
        check_data_dir(data_dir),
        check_port_free(host, port),
        *check_core_tabular_deps(),
    ]
    if not any(c.status == "error" for c in fatal_checks):
        return

    print(
        _red(
            _bold(
                _u(
                    "Cannot start OpenConstructionERP — pre-flight checks failed:",
                    "Cannot start OpenConstructionERP - pre-flight checks failed:",
                )
            )
        )
    )
    print()
    for c in fatal_checks:
        c.print()
    print()
    print(_dim("Run 'openconstructionerp doctor' for full diagnostics."))
    print(_dim(f"Troubleshooting: {TROUBLESHOOTING_URL}"))
    sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the OpenConstructionERP server."""
    data_dir = _data_dir_from_args(args)

    # ``serve --no-demo``: skip demo accounts / showcase projects for this
    # start AND remember the choice in the data dir so subsequent bare
    # starts honour it too (read by app.main's demo seeder when SEED_DEMO
    # is not set in the environment).
    if getattr(args, "no_demo", False):
        from app.core.demo_seed import write_demo_seed_choice

        os.environ["SEED_DEMO"] = "false"
        write_demo_seed_choice(False, data_dir)

    # ``serve --demo``: the mirror of ``--no-demo``. Force demo seeding on and
    # clear any persisted opt-out so the demo sign-in block returns on the next
    # start. Explicit and idempotent, so it is safe to pass on every start.
    if getattr(args, "demo", False):
        from app.core.demo_seed import write_demo_seed_choice

        os.environ["SEED_DEMO"] = "true"
        write_demo_seed_choice(True, data_dir)

    # The fatal preflight runs BEFORE _setup_env, and the order is the whole
    # point. _setup_env boots the embedded PostgreSQL cluster, which on a first
    # run means an initdb: about twenty seconds and forty megabytes under the
    # data dir. Every one of these four checks is independent of it, and two of
    # them describe conditions that make the boot pointless. Running them after
    # meant a first-time user with something else on port 8080 - the single most
    # common thing to be wrong on a machine we have never seen - waited out the
    # whole initdb to be told about a conflict that costs microseconds to
    # detect. Worse, check_data_dir never got to speak at all: _setup_env's own
    # unguarded data_dir.mkdir() is three lines into the function, so an
    # unwritable path raised FileNotFoundError there and the user got a pathlib
    # traceback instead of the sentence naming --data-dir that this check exists
    # to print.
    _run_fatal_preflight(data_dir, args.host, args.port)

    _setup_env(data_dir, args.host, args.port)

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
        print(
            _dim(
                _u(
                    "  Starting server… first run may take up to 30 seconds.",
                    "  Starting server... first run may take up to 30 seconds.",
                )
            )
        )
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

    # Emit a boot-progress marker the desktop launcher parses to advance its
    # visible startup checklist. The embedded-PG and (where applicable) schema
    # stages already emitted theirs; this one means "the HTTP server is coming
    # up", after which the launcher's own /api/health probe drives the rest.
    try:
        from app.core.embedded_pg import emit_stage

        emit_stage("server", "start", "Starting the application server")
    except Exception:  # noqa: BLE001
        pass

    def _emit_server_fail(exc: BaseException) -> None:
        """Surface a fatal serve() error as a machine-readable failure marker.

        The desktop launcher latches this ``STAGE:server:fail`` line as the real
        startup cause, so the embedded-PostgreSQL shutdown output that follows a
        crash can no longer bury it. Emit the marker first (flushed) so it wins
        the race against that shutdown noise; the full traceback still goes to
        stderr for the log file. Best effort - never raises.
        """
        import traceback

        reason = f"{type(exc).__name__}: {exc}".replace("\n", " ").replace("\r", " ").strip()
        if len(reason) > 180:
            reason = reason[:177] + "..."
        try:
            from app.core.embedded_pg import emit_stage

            emit_stage("server", "fail", reason)
        except Exception:  # noqa: BLE001
            # Even without the helper, get the raw marker out on stdout.
            print(f"STAGE:server:fail:{reason}", flush=True)
        try:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass

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
        _emit_server_fail(exc)
        print()
        print(_red(_bold("Server failed to start:")) + f" {exc}")
        arrow = _u("\u2192", "->")
        if "address already in use" in str(exc).lower() or "10048" in str(exc):
            print(
                _dim(
                    f"  {arrow} Port {args.port} is already in use. Try: openconstructionerp serve --port {args.port + 1}"
                )
            )
        else:
            print(_dim(f"  {arrow} See: {TROUBLESHOOTING_URL}"))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        _emit_server_fail(exc)
        arrow = _u("\u2192", "->")
        print()
        print(_red(_bold("Unexpected startup error:")) + f" {type(exc).__name__}: {exc}")
        print(_dim(f"  {arrow} Run 'openconstructionerp doctor' to diagnose."))
        print(_dim(f"  {arrow} Report this at: {ISSUES_URL}"))
        sys.exit(1)


def _register_all_module_models() -> tuple[int, int, list[tuple[str, str]]]:
    """Import every ``app.modules.*.models`` so ``create_all`` sees the full schema.

    Dynamic discovery from the package tree, mirroring app.main's startup hook.
    A hand-maintained list used to live in the CLI and rotted: it omitted
    ``file_versions``, so ``oe_markups_markup``'s foreign key to
    ``oe_file_version`` could not resolve and ``create_all`` aborted the whole
    schema on a fresh database. Discovering models from ``app.modules`` makes
    that class of "forgot to add it to the list" bug impossible.

    Returns ``(imported_ok, modules_with_models, failed_imports)``.
    """
    import importlib
    import pkgutil

    from app import modules as _modules_pkg

    # Core tables that live outside app.modules (oe_activity_log, used by the
    # FSM log_activity helper) are registered explicitly, the same as main.py.
    try:
        from app.core import audit as _audit_core  # noqa: F401
        from app.core import audit_log as _audit_log_core  # noqa: F401

        # oe_data_repair_ledger, same case: declared in app.core, so the
        # app.modules loop below never reaches it and create_all would not
        # build it. Without the table the repairs still run and only the record
        # of them is lost, which is the failure that module exists to stop.
        from app.core import data_repairs as _data_repairs_core  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.warning("schema: core audit models not registered: %s", exc)

    imported_ok = 0
    total = 0
    failed: list[tuple[str, str]] = []
    for _m in pkgutil.iter_modules(_modules_pkg.__path__):
        if not _m.ispkg:
            continue
        models_mod = f"app.modules.{_m.name}.models"
        try:
            importlib.import_module(models_mod)
            imported_ok += 1
            total += 1
        except ModuleNotFoundError as exc:
            # No models.py in this module is fine - skip it. A *different*
            # missing import inside models.py is a real bug, so record it.
            if exc.name != models_mod:
                total += 1
                failed.append((_m.name, f"ModuleNotFoundError: {exc}"))
                logger.warning("schema: failed to import %s: %s", models_mod, exc)
        except Exception as exc:  # noqa: BLE001
            # Syntax error, attribute error, etc. inside models.py - real bug.
            total += 1
            failed.append((_m.name, f"{type(exc).__name__}: {exc}"))
            logger.warning("schema: %s while importing %s: %s", type(exc).__name__, models_mod, exc)
    return imported_ok, total, failed


def cmd_init_db(args: argparse.Namespace) -> None:
    """Initialise the data directory and create the database schema."""
    data_dir = _data_dir_from_args(args)
    reset = bool(getattr(args, "reset", False))

    from app.core import embedded_pg

    # Honour --reset BEFORE _setup_env boots the cluster, so the embedded
    # PostgreSQL comes up against a clean data directory. An external
    # DATABASE_URL is left untouched: the operator manages remote resets.
    if reset and embedded_pg.is_requested():
        pgdata = data_dir / "pgdata"
        if pgdata.exists():
            import shutil

            shutil.rmtree(pgdata, ignore_errors=True)
            print(_amber(f"Reset: deleted previous database cluster at {pgdata}"))
        # Sweep away a stray pre-6.0 SQLite file too, so a later boot does not
        # auto-migrate it into the fresh cluster.
        legacy = data_dir / "openestimate.db"
        for suffix in ("", "-shm", "-wal"):
            sibling = legacy.with_name(legacy.name + suffix)
            try:
                sibling.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("init-db --reset: could not delete %s: %s", sibling, exc)

    print(
        _u("Initialising data directory at ", "Initialising data directory at ")
        + f"{_bold(str(data_dir))}"
        + _u("…", "...")
    )
    _setup_env(data_dir, DEFAULT_HOST, DEFAULT_PORT)

    # Create every module's tables now so the first `serve` starts instantly
    # without table-creation lag.
    import asyncio

    # Register every module's SQLAlchemy models before create_all, by dynamic
    # discovery (see _register_all_module_models). This used to be a
    # hand-maintained list that rotted and omitted file_versions, which made
    # create_all abort on the oe_markups_markup -> oe_file_version foreign key.
    # The user saw the failure during init-db; the same omission would have
    # left "no such table" errors at runtime had create_all not caught it.
    imported_ok, total, failed_imports = _register_all_module_models()

    async def _create() -> None:
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # create_all only adds missing tables; patch any columns added to
        # pre-existing tables across an upgrade (the PostgreSQL counterpart to
        # what Alembic does for external deployments).
        try:
            from app.core.postgres_migrator import postgres_auto_migrate

            await postgres_auto_migrate(engine, Base)
        except Exception as exc:  # noqa: BLE001
            logger.warning("init-db: postgres_auto_migrate skipped: %s", exc)
        # The heal numbers a freshly added oe_progress_entry.seq in heap order,
        # which is not the order the Alembic migration gives the same rows and
        # decides which reading the progress module calls current. Same repair
        # as the one the app runs at boot; here so init-db leaves the database
        # in the state the first serve would have reached anyway.
        try:
            from app.modules.progress.seq_repair import repair_progress_entry_seq

            async with engine.begin() as conn:
                await repair_progress_entry_seq(conn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("init-db: progress seq repair skipped: %s", exc)
        # An upgraded database keeps the naive classified_at that this version
        # declares aware, because the auto-migrator above only adds, never
        # retypes. Widen it here so the column matches the model on the
        # installations that have one already.
        try:
            from app.modules.project_route.tz_repair import widen_classified_at

            async with engine.begin() as conn:
                await widen_classified_at(conn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("init-db: classified_at widening skipped: %s", exc)
        # The data half of an upgrade. The heal above moves the schema and
        # rewrites no rows, so a migration that backfills or renames never runs
        # on any install brought up this way. Same registry the first serve
        # would run, here so init-db leaves the database in the state that boot
        # would have reached anyway - see app.core.data_repairs. Every entry is
        # idempotent, so running it in both places costs a scan that finds
        # nothing the second time.
        try:
            from app.core.data_repairs import run_data_repairs
            from app.database import async_session_factory

            repair_report = await run_data_repairs(async_session_factory, app_version=_resolve_version())
            if repair_report.failed:
                logger.error(
                    "init-db: data repairs FAILED: %s. Rows this release expects to have been "
                    "corrected are still wrong; the causes are logged above and the repairs are "
                    "retried on the next start.",
                    ", ".join(repair_report.failed),
                )
            elif repair_report.rows_changed:
                logger.info("init-db: data repairs rewrote %d row(s)", repair_report.rows_changed)
        except Exception as exc:  # noqa: BLE001
            logger.error("init-db: data repairs could not run: %s", exc, exc_info=True)
        # Provision row-level-security roles + policies when enabled. No-op
        # while settings.rls_enforce is off, so a default init-db is unchanged.
        try:
            from app.core.rls_setup import provision_rls

            await provision_rls(engine, Base)
        except Exception as exc:  # noqa: BLE001
            logger.warning("init-db: RLS provisioning skipped: %s", exc)

    try:
        asyncio.run(_create())
    except Exception as exc:
        print(_red(f"Database initialisation failed: {exc}"))
        print(_dim(f"  {_u('\u2192', '->')} Run 'openconstructionerp doctor' for diagnostics."))
        sys.exit(1)

    print()
    print(f"  {_dim('Modules:')}  imported {imported_ok}/{total} module models")

    if failed_imports:
        print()
        print(_red(_bold(f"  {len(failed_imports)} module(s) failed to import:")))
        for name, err in failed_imports:
            print(f"    - {_bold(name)}: {_dim(err)}")
        print()
        print(_red("Schema may be incomplete. Reinstall the package or check the error above."))
        print(
            _dim(
                f"  {_u('\u2192', '->')} "
                + _repair_hint(
                    "pip install --upgrade --force-reinstall openconstructionerp",
                    "Reinstall the app from its installer",
                )
            )
        )
        print(_dim(f"  {_u('\u2192', '->')} Then run 'openconstructionerp doctor' to verify."))
        sys.exit(1)

    print()
    print(_green(_bold("Ready.")))
    if embedded_pg.is_running():
        print(f"  {_dim('Database:')} embedded PostgreSQL at {data_dir / 'pgdata'}")
    else:
        print(f"  {_dim('Database:')} external PostgreSQL (DATABASE_URL)")
    print(f"  {_dim('Vectors:')}  {data_dir / 'vectors'}")
    print(f"  {_dim('Uploads:')}  {data_dir / 'uploads'}")
    print()
    print(f"Next: {_amber('openconstructionerp serve')}")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run pre-flight checks and report OK / WARN / ERROR per item."""
    data_dir = _data_dir_from_args(args)

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
        print(_dim("Fix the errors above, then run 'openconstructionerp serve'."))
        print(_dim(f"Docs: {TROUBLESHOOTING_URL}"))
        sys.exit(1)
    elif warns:
        print(
            _yellow(_bold(f"  {len(warns)} warning(s)"))
            + _dim(_u(" \u2014 non-fatal, server will run", " - non-fatal, server will run"))
        )
        print()
        print(f"Run: {_amber('openconstructionerp serve')}")
    else:
        print(_green(_bold("  All checks passed.")))
        print()
        print(f"Run: {_amber('openconstructionerp serve')}")


def cmd_version(_args: argparse.Namespace) -> None:
    """Print version information."""
    version = _resolve_version()

    print(f"OpenConstructionERP v{version}")
    print(f"Python {sys.version.split()[0]} ({sys.platform})")
    # This is the line people paste when something is wrong with an install, so
    # each label has to name what it actually shows. "Site-packages" used to be
    # printed against the interpreter's own directory, which is Scripts on
    # Windows and bin elsewhere, so anyone who followed it went looking for the
    # package where the package is not. The data directory is here for the same
    # reason: it is the other thing support asks for, and printing it is also
    # how an operator confirms their data-dir override was taken.
    print(f"Installed at: {Path(__file__).resolve().parent.parent}")
    print(f"Interpreter: {sys.executable}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")
    print(f"Docs: {DOCS_URL}")


def cmd_upgrade(args: argparse.Namespace) -> None:
    """Pip-upgrade openconstructionerp inside *this* interpreter's environment.

    Issue #96: users who installed via the Windows installer get a launcher
    (``start.bat``) that points at a private venv under
    ``%LOCALAPPDATA%\\OpenConstructionERP\\venv``. Running ``pip install
    --upgrade openconstructionerp`` in any other shell upgrades the user's
    GLOBAL Python - the venv keeps its old wheel, and the launcher keeps
    reporting the old version even though pip claims success. This command
    avoids the trap by always invoking ``sys.executable -m pip`` so the
    upgrade lands in the same env that ``serve`` runs in.
    """
    import subprocess

    # Imported here, not at module scope: this file keeps its top-level imports
    # to the standard library so the CLI starts fast.
    from app.core.self_upgrade import RELEASES_URL, is_frozen_build

    print()
    print(_bold(_u("OpenConstructionERP \u2014 upgrade", "OpenConstructionERP - upgrade")))

    # In the PyInstaller desktop build ``sys.executable`` is the frozen binary,
    # not an interpreter, so the tokens below would come straight back into this
    # CLI as ``openconstructionerp pip install ...`` and argparse would answer
    # ``invalid choice: 'pip'`` (issue #403). The bundle carries no pip; the
    # installer replaces the whole app.
    if is_frozen_build():
        print()
        print(_red(_bold("  This build cannot upgrade itself with pip.")))
        print(_dim("Download the latest installer and run it over this install:"))
        print(_dim(f"  {RELEASES_URL}"))
        print(_dim("Your projects and settings stay where they are."))
        sys.exit(1)

    # pip is about to replace files in site-packages, and on this install some
    # of those files are executing right now: the embedded PostgreSQL binaries
    # live under pixeltable_pgserver, and compiled extensions are loaded into
    # any running server. On Windows the running image is locked, so pip fails
    # partway and leaves an install that is neither the old version nor the new
    # one. Elsewhere it succeeds and the running process quietly becomes a
    # mixture of both, because this codebase imports inside functions in many
    # places and every later import reads the new file.
    #
    # Asking first costs nothing and turns a torn install into one clear line.
    data_dir = _data_dir_from_args(args)
    try:
        from app.core.embedded_pg import cluster_postmaster_pid

        live_pid = cluster_postmaster_pid(data_dir)
    except Exception:  # noqa: BLE001
        live_pid = None

    if live_pid is not None:
        print()
        print(_red(_bold("  The application is still running.")))
        print(_dim(f"The local database is being served by process {live_pid} from:"))
        print(_dim(f"  {data_dir / 'pgdata'}"))
        print()
        print(_dim("Upgrading now would replace files that process is executing from."))
        print(_dim("Close the app (or stop `openconstructionerp serve`), then run this again."))
        sys.exit(1)

    target = "openconstructionerp"
    if args.version:
        target = f"openconstructionerp=={args.version}"

    print(_dim(f"Interpreter: {sys.executable}"))
    print(_dim(f"Installing:  {target}"))
    print()

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", target]
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        print(_red(f"pip not found in this interpreter: {exc}"))
        sys.exit(1)

    if result.returncode != 0:
        print()
        print(_red(_bold(f"  Upgrade failed (exit {result.returncode})")))
        print(_dim("Try: python -m pip install --upgrade openconstructionerp"))
        sys.exit(result.returncode)

    new_version = _resolve_version()
    print()
    print(_green(_bold(f"  Upgraded to v{new_version}")))
    print(_dim("Restart your launcher (start.bat / openconstructionerp serve) to pick it up."))


def _resolve_version() -> str:
    """Best-effort version lookup shared by welcome, version and upgrade.

    Settings first, package metadata second. It used to be the other way round,
    and that made this command disagree with the server it was standing next
    to. ``importlib.metadata`` reports whatever distribution is installed in
    the environment, which on a source checkout with any earlier
    ``pip install openconstructionerp`` in it is not the code that is running:
    this printed v15.2.0 for a tree at 15.9.1 while ``/api/health`` on the same
    interpreter correctly said 15.9.1. Settings resolves through
    ``config._detect_version``, which prefers the pyproject beside the running
    source and exists for exactly this reason, so asking it puts the two back
    in agreement. The metadata lookup stays as the fallback, which is what a
    real installed copy hits anyway since there is no source tree above it.

    ``doctor`` still asks the metadata directly and should: the question there
    is whether a distribution is installed at all, not what the running code
    is.

    The Settings branch reads the field rather than the model because
    ``app_version`` is declared with ``default_factory``, and a field declared
    that way has no ``default``: pydantic stores the ``PydanticUndefined``
    sentinel there. That sentinel has a ``__str__``, so the old code did not
    raise and did not fall through to "unknown" either. It printed
    ``OpenConstructionERP vPydanticUndefined`` at the one moment that path
    exists for. Both branches are kept because either declaration is
    legitimate and this function must not break the next time somebody changes
    which one is used.
    """
    try:
        from app.config import Settings

        field = Settings.model_fields["app_version"]
        if field.default_factory is not None:
            return str(field.default_factory())  # type: ignore[call-arg]
        return str(field.default)
    except Exception:
        try:
            from importlib.metadata import version as _v

            return _v("openconstructionerp")
        except Exception:
            return "unknown"


def print_welcome(*, next_command_hint: bool = True) -> None:
    """Fast, zero-network welcome screen.

    Shown on the first bare ``openconstructionerp`` invocation and when
    the user runs ``openconstructionerp welcome`` explicitly. Tells them
    the single command that starts everything, the demo login, and where
    to ask questions when something goes wrong.

    ``next_command_hint`` distinguishes the two contexts. When True the
    user typed ``welcome`` and no server is starting, so we tell them the
    command that does. When False this is the first-run bare command and
    the server is about to auto-start, so we say so instead.
    """
    version = _resolve_version()
    bar = _bar()
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    print()
    print(_amber(_BANNER_ART))
    print()
    print(f"  {_bold('OpenConstructionERP')} {_dim('v' + version)}")
    print(f"  {_dim('Open-source construction cost estimation platform')}")
    print()
    if next_command_hint:
        print(f"  {bar}  {_bold('To start, run one command')}")
        print(f"  {bar}     {_amber('openconstructionerp')}")
        print(f"  {bar}  {_dim('It sets up the database, loads the demo and opens your browser.')}")
        print(f"  {bar}")
        print(f"  {bar}  {_dim('Command not found? This always works, no PATH needed:')}")
        print(f"  {bar}     {_amber('python -m openconstructionerp')}")
    else:
        print(f"  {bar}  {_bold('Setting things up for you')}")
        print(f"  {bar}  {_dim('Creating the database and loading the demo. The server starts in a moment.')}")
    print(f"  {bar}")
    print(f"  {bar}  {_bold('Then log in')}")
    print(f"  {bar}     {_amber(url)}")
    print(f"  {bar}     demo@openconstructionerp.com  {_dim('/')}  DemoPass1234!")
    print()
    print(f"  {_dim('Advanced:')}  openconstructionerp serve {_dim('|')} init-db {_dim('|')} doctor {_dim('|')} --help")
    print()
    print(f"  {_bold('Help and community')}")
    print(f"    {_dim('Docs'.ljust(10))} {DOCS_URL}")
    print(f"    {_dim('GitHub'.ljust(10))} {GITHUB_URL}")
    print(f"    {_dim('Community'.ljust(10))} {COMMUNITY_URL} {_dim('(Telegram)')}")
    print()
    if next_command_hint:
        print(
            f"  {_dim('Tip: run')} {_amber('openconstructionerp')} {_dim('(or')} {_amber('python -m openconstructionerp')}{_dim(') any time to start the server.')}"
        )
        print()


def cmd_welcome(_args: argparse.Namespace) -> None:
    """Print the welcome screen and exit - no server, no I/O."""
    print_welcome(next_command_hint=True)


def _prompt_open_browser(url: str, default_open: bool = True) -> bool:
    """Ask whether to open the browser on first-run.

    Returns True if the user presses ``o`` (or just Enter when the
    default is open), False if they decline. Safe against non-TTY
    invocations (CI, piped input) - returns ``default_open`` and moves
    on without blocking.

    The prompt is deliberately short so the user can hit Enter in under
    a second without reading the whole sentence.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return default_open

    default_hint = "[O/n]" if default_open else "[o/N]"
    prompt = f"  {_bold('Open')} {_amber(url)} {_dim('in your browser now?')} {_dim(default_hint)} "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer == "":
        return default_open
    return answer.startswith("o") or answer in ("y", "yes", "да", "д")


def _prompt_seed_demo() -> bool | None:
    """Ask on first run whether to load the demo projects.

    Returns ``True`` / ``False`` for an explicit answer (default Yes on a
    bare Enter), or ``None`` when there is no interactive terminal (CI,
    piped input, service start) - callers keep the current default
    behaviour in that case and do not persist anything.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.environ.get("CI"):
        return None

    prompt = f"  {_bold('Load demo projects')} {_dim('to explore the app?')} {_dim('[Y/n]')} "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if answer == "":
        return True
    return not (answer.startswith("n") or answer in ("нет", "н"))


def cmd_seed(args: argparse.Namespace) -> None:
    """Load demo data into the database."""
    data_dir = _data_dir_from_args(args)
    _setup_env(data_dir, DEFAULT_HOST, DEFAULT_PORT)

    import asyncio

    async def _run_seed() -> None:
        # Ensure the schema exists before seeding: a fresh PostgreSQL database
        # has no tables until create_all runs. Register EVERY module's models
        # (not just a handful) so create_all builds the complete schema and
        # every cross-module foreign key resolves.
        from app.database import Base, engine

        _register_all_module_models()

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


# ── Module management (install / list / uninstall) ─────────────────────────
# A module is a Python package under ``app/modules/`` that carries a
# ``manifest.py`` exposing a module-level ``manifest = ModuleManifest(...)``.
# The loader (``app.core.module_loader``) discovers modules by scanning that
# directory for ``manifest.py`` and registers each by ``manifest.name`` (e.g.
# ``oe_boq``). The on-disk directory name is ``manifest.name`` with the
# ``oe_`` prefix stripped (``oe_boq`` -> ``boq``), which is the convention
# ``_load_module`` uses to resolve the importable package path. These commands
# extract / remove modules into exactly that directory so the loader picks
# them up on the next server start.


def _modules_dir() -> Path:
    """Return the directory the module loader scans for modules.

    Imports the loader so we always agree with it on the location, instead of
    re-deriving the path here and risking drift.
    """
    from app.core.module_loader import MODULES_DIR

    return MODULES_DIR


def _module_dir_name(manifest_name: str) -> str:
    """Map a manifest name to its on-disk package directory name.

    Mirrors ``ModuleLoader._load_module`` (``dir_name = name.removeprefix('oe_')``).
    """
    return manifest_name.removeprefix("oe_")


def _read_manifest_name(source: str) -> str | None:
    """Extract ``manifest.name`` from a ``manifest.py`` source string.

    Parsed statically with ``ast`` rather than imported, so installing a module
    never executes untrusted code just to learn its name. Looks for a top-level
    assignment ``<target> = ModuleManifest(... name="...", ...)`` and returns the
    literal ``name`` keyword. Returns ``None`` if it cannot be found.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if callee != "ModuleManifest":
            continue
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
    return None


def cmd_module_install(args: argparse.Namespace) -> None:
    """Install a module from a .zip archive into the modules directory."""
    import shutil
    import tempfile
    import zipfile

    # One shared, hardened zip-safety implementation (no weaker fork). Imported
    # here rather than at module top so the CLI's pre-import env setup
    # (_setup_env, which must run before any ``app`` import builds the DB
    # engine) is never pre-empted by importing this command's helper.
    from app.core.partner_pack._safe_extract import (
        UnsafeArchiveError,
        is_unsafe_zip_member,
        safe_extract_all,
    )

    zip_path = Path(args.zip).expanduser().resolve()

    if not zip_path.exists():
        print(_red(f"Archive not found: {zip_path}"))
        sys.exit(1)

    if not zipfile.is_zipfile(zip_path):
        print(_red(f"Not a valid zip archive: {zip_path}"))
        sys.exit(1)

    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if not infos:
            print(_red("Archive is empty."))
            sys.exit(1)

        # 1. Reject any unsafe member before touching the filesystem.
        for info in infos:
            reason = is_unsafe_zip_member(info)
            if reason is not None:
                print(_red(f"Refusing to install - unsafe archive member ({reason})."))
                sys.exit(1)

        # 2. Require exactly one top-level package directory. Every member must
        #    live under it (a flat archive with files at the root is rejected).
        top_levels: set[str] = set()
        for info in infos:
            first = info.filename.split("/", 1)[0]
            if first:
                top_levels.add(first)
        if len(top_levels) != 1:
            print(
                _red(
                    "Archive must contain exactly one top-level package directory "
                    f"(found {len(top_levels)}: {', '.join(sorted(top_levels)) or 'none'})."
                )
            )
            sys.exit(1)
        top = next(iter(top_levels))

        # 3. The top-level entry must be a directory, not a single file.
        if not any(i.filename.rstrip("/") != top for i in infos):
            print(_red(f"Top-level entry {top!r} is a file, not a package directory."))
            sys.exit(1)

        # 4. Locate the manifest at the top level: ``<top>/manifest.py``.
        manifest_arcname = f"{top}/manifest.py"
        names = {i.filename for i in infos}
        if manifest_arcname not in names:
            print(
                _red(
                    f"No manifest found at {manifest_arcname!r}. A module package must contain a top-level manifest.py."
                )
            )
            sys.exit(1)

        # 5. Read the module name from the manifest (static parse, no exec).
        try:
            manifest_src = zf.read(manifest_arcname).decode("utf-8")
        except (KeyError, UnicodeDecodeError) as exc:
            print(_red(f"Could not read {manifest_arcname}: {exc}"))
            sys.exit(1)

        module_name = _read_manifest_name(manifest_src)
        if not module_name:
            print(
                _red('Could not determine the module name from manifest.py (expected ModuleManifest(name="...", ...)).')
            )
            sys.exit(1)

        # 6. Resolve the canonical on-disk directory name and target path.
        dir_name = _module_dir_name(module_name)
        modules_dir = _modules_dir()
        target = modules_dir / dir_name

        if target.exists():
            if not args.force:
                print(
                    _red(f"Module '{module_name}' already installed at {target}.") + _dim(" Use --force to overwrite.")
                )
                sys.exit(1)
            shutil.rmtree(target)

        # 7. Safe extraction into a temp staging dir, then atomically move the
        #    package into place under its canonical directory name. Staging
        #    first means a mid-extract failure never leaves a half-written
        #    module in the loader's scan path. ``safe_extract_all`` re-validates
        #    each member at write time (defence in depth against a crafted
        #    ZipInfo whose name slipped past the up-front check).
        modules_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="oe_module_install_"))
        try:
            try:
                safe_extract_all(zf, staging)
            except UnsafeArchiveError as exc:
                print(_red(f"Refusing to install - {exc}."))
                sys.exit(1)

            staged_pkg = staging / top
            if not staged_pkg.is_dir():
                print(_red("Extraction did not produce the expected package directory."))
                sys.exit(1)

            shutil.move(str(staged_pkg), str(target))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    print(_green(_bold(f"Installed module: {module_name}")) + _dim(f"  ({target})"))
    print("Restart the server to load the module.")


def _discover_manifests() -> dict[str, object]:
    """Discover all module manifests via the real loader, return name -> manifest.

    Uses a fresh ``ModuleLoader`` (not the global singleton) so a CLI ``list``
    never mutates shared process state.
    """
    from app.core.module_loader import ModuleLoader

    loader = ModuleLoader()
    loader.discover()
    return dict(loader._manifests)


def cmd_module_list(_args: argparse.Namespace) -> None:
    """List discovered modules with version and enabled/core status."""
    from app.core.module_state import load_module_states

    manifests = _discover_manifests()
    if not manifests:
        print(_dim("No modules found."))
        return

    states = load_module_states()

    rows: list[tuple[str, str, str, str]] = []
    for name in sorted(manifests):
        manifest = manifests[name]
        version = getattr(manifest, "version", "?")
        category = getattr(manifest, "category", "")
        is_core = category == "core"
        # A non-core module is disabled only if persisted state says so.
        state = states.get(name)
        enabled = True if state is None else state.enabled
        if is_core:
            status = "core"
        else:
            status = "enabled" if enabled else "disabled"
        rows.append((name, version, category, status))

    name_w = max((len(r[0]) for r in rows), default=4)
    ver_w = max((len(r[1]) for r in rows), default=7)
    cat_w = max((len(r[2]) for r in rows), default=8)

    header = f"  {'NAME'.ljust(name_w)}  {'VERSION'.ljust(ver_w)}  {'CATEGORY'.ljust(cat_w)}  STATUS"
    print(_bold(header))
    for name, version, category, status in rows:
        if status == "core":
            badge = _dim("core")
        elif status == "enabled":
            badge = _green("enabled")
        else:
            badge = _yellow("disabled")
        print(f"  {name.ljust(name_w)}  {version.ljust(ver_w)}  {category.ljust(cat_w)}  {badge}")

    print()
    print(_dim(f"{len(rows)} module(s) in {_modules_dir()}"))


def cmd_module_uninstall(args: argparse.Namespace) -> None:
    """Remove an installed module's package directory."""
    import shutil

    requested = args.name
    manifests = _discover_manifests()

    # Accept either the manifest name (oe_foo) or the directory name (foo).
    manifest = manifests.get(requested)
    if manifest is None:
        manifest = manifests.get(f"oe_{requested}")

    if manifest is None:
        print(_red(f"Module '{requested}' is not installed."))
        print(_dim("Run 'openconstructionerp module list' to see installed modules."))
        sys.exit(1)

    manifest_name = getattr(manifest, "name", requested)
    is_core = getattr(manifest, "category", "") == "core"
    auto_install = bool(getattr(manifest, "auto_install", False))

    if (is_core or auto_install) and not args.force:
        kind = "core" if is_core else "auto-install"
        print(
            _red(f"Refusing to uninstall '{manifest_name}' - it is a {kind} module.")
            + _dim(" Use --force to remove it anyway.")
        )
        sys.exit(1)

    dir_name = _module_dir_name(manifest_name)
    target = _modules_dir() / dir_name
    if not target.exists():
        print(_red(f"Module directory not found: {target}"))
        sys.exit(1)

    shutil.rmtree(target)
    print(_green(_bold(f"Uninstalled module: {manifest_name}")) + _dim(f"  ({target})"))
    print("Restart the server to apply the change.")


def cmd_module(args: argparse.Namespace) -> None:
    """Dispatch ``module`` sub-actions; print help when none is given."""
    action = getattr(args, "module_action", None)
    if action == "install":
        cmd_module_install(args)
    elif action == "list":
        cmd_module_list(args)
    elif action == "uninstall":
        cmd_module_uninstall(args)
    else:
        # No sub-action: print the module group's help.
        args._module_parser.print_help()


# ── Partner-pack scaffolding (pack new) ─────────────────────────────────────
# A partner pack dropped into ``<data-dir>/packs/`` is *declarative*: a
# ``manifest.json`` (a serialized PartnerPackManifest) plus its assets. Unlike
# business modules it ships NO Python and is never imported/executed by the
# core. ``pack new`` emits a minimal, valid, immediately-discoverable folder so
# a partner can edit the placeholders and drop it straight into the data dir.

_PACK_PLACEHOLDER_LOGO_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 64" role="img"
     aria-label="Partner logo placeholder">
  <rect width="240" height="64" rx="8" fill="#0F2C5F"/>
  <text x="120" y="40" font-family="Arial, sans-serif" font-size="22"
        font-weight="700" fill="#FFFFFF" text-anchor="middle">{partner}</text>
</svg>
"""

_PACK_ONBOARDING_YAML = """\
# {slug} - first-login onboarding script (declarative).
#
# Replaces the default OnboardingWizard steps when this pack is active. Each
# step is rendered by the frontend OnboardingWizard; `kind` maps to an existing
# step renderer (intro | form | choice | external_link | summary). Edit freely.

version: 2
pack: {slug}
estimated_minutes: 5

steps:
  - id: welcome
    kind: intro
    skippable: false
    title_i18n:
      en: "Welcome"
    body_i18n:
      en: "This OpenConstructionERP install is pre-configured by {partner}. Replace these placeholder steps with your own onboarding flow."

  - id: done
    kind: summary
    skippable: false
    title_i18n:
      en: "All set"
    body_i18n:
      en: "You are ready to start. Edit onboarding.yaml in this pack to customise these steps."
"""

_PACK_README = """\
# {slug} - OpenConstructionERP partner pack

This is a declarative partner pack (Shape A). It carries only presets:
branding, default locale, currency/tax defaults, module visibility and an
onboarding script. It contains no Python and is never executed by the core.

## Files

- `manifest.json` - the serialized PartnerPackManifest (the only required file)
- `logo.svg` - partner logo, streamed on the co-brand badge
- `onboarding.yaml` - optional first-login onboarding script
- `README.md` - this file

## Install

Drop this whole folder (or a `.zip` of it) into your install's data directory
under `packs/`:

    <data-dir>/packs/{slug}/manifest.json

Then in the app go to the Modules page, Partner Packs tab, click Rescan and
Apply, or upload the `.zip` via the in-app installer. The default data dir is
`~/.openestimate` (or wherever your database lives).

Edit the placeholders in `manifest.json` (partner name, colours, locale,
currency, CWICR regions, validation rule packs) before shipping.
"""


def _scaffold_pack_manifest_json(slug: str) -> str:
    """Build a valid serialized ``PartnerPackManifest`` JSON for ``slug``.

    Constructs a real :class:`PartnerPackManifest` with sensible placeholders so
    the emitted file is guaranteed to validate (and therefore be discoverable),
    then serialises it with indentation for easy hand-editing.
    """
    from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

    partner_display = slug.replace("-", " ").title()
    manifest = PartnerPackManifest(
        slug=slug,
        partner_name=partner_display,
        partner_url="https://example.com",
        pack_version="0.1.0",
        description=f"Preset bundle for {partner_display}. Edit this manifest before shipping.",
        default_locale="en",
        additional_locales={},
        cwicr_regions=[],
        default_currency="EUR",
        default_tax_template=None,
        validation_rule_packs=[],
        default_modules=[],
        hidden_modules=[],
        branding=PartnerBranding(
            primary_color="#0F2C5F",
            accent_color=None,
            logo_path="logo.svg",
            favicon_path=None,
            powered_by_text=None,
        ),
        onboarding_script_path="onboarding.yaml",
        metadata={"country": "", "support_email": "info@example.com"},
    )
    return manifest.model_dump_json(indent=2)


def cmd_pack_new(args: argparse.Namespace) -> None:
    """Scaffold a new declarative partner pack folder ready to drop in."""
    from app.core.partner_pack.manifest import PartnerPackManifest

    slug = args.slug.strip()

    # Validate the slug against the same pattern the manifest enforces, so we
    # fail fast with a clear message instead of emitting a pack that the loader
    # would later reject.
    slug_field = PartnerPackManifest.model_fields["slug"]
    pattern = next((m.pattern for m in slug_field.metadata if hasattr(m, "pattern")), r"^[a-z][a-z0-9\-]{2,40}$")
    import re

    if not re.match(pattern, slug):
        print(_red(f"Invalid pack slug {slug!r}."))
        print(_dim(f"  Must match {pattern} (lowercase, starts with a letter, 3-41 chars, hyphens allowed)."))
        sys.exit(1)

    out_root = Path(args.out).expanduser().resolve() if args.out else Path.cwd()
    target = out_root / slug

    if target.exists():
        if not args.force:
            print(_red(f"Target already exists: {target}.") + _dim(" Use --force to overwrite."))
            sys.exit(1)
        import shutil

        shutil.rmtree(target)

    partner_display = slug.replace("-", " ").title()
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(_scaffold_pack_manifest_json(slug), encoding="utf-8")
        (target / "logo.svg").write_text(_PACK_PLACEHOLDER_LOGO_SVG.format(partner=partner_display), encoding="utf-8")
        (target / "onboarding.yaml").write_text(
            _PACK_ONBOARDING_YAML.format(slug=slug, partner=partner_display), encoding="utf-8"
        )
        (target / "README.md").write_text(_PACK_README.format(slug=slug), encoding="utf-8")
    except OSError as exc:
        print(_red(f"Could not write pack files: {exc}"))
        sys.exit(1)

    # Sanity check: the file we just wrote must validate, so "new" never emits a
    # pack the loader would silently skip.
    try:
        PartnerPackManifest.model_validate_json((target / "manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - defensive; placeholders are valid by construction
        print(_red(f"Scaffolded manifest failed validation: {exc}"))
        sys.exit(1)

    print(_green(_bold(f"Created partner pack: {slug}")) + _dim(f"  ({target})"))
    print()
    print(f"  {_dim('manifest.json')}    serialized PartnerPackManifest (edit the placeholders)")
    print(f"  {_dim('logo.svg')}         placeholder partner logo")
    print(f"  {_dim('onboarding.yaml')}  first-login onboarding stub")
    print(f"  {_dim('README.md')}        how to install")
    print()
    print(_bold("Next steps"))
    print(f"  1. Edit {_amber(str(target / 'manifest.json'))} (partner name, colours, locale, currency).")
    print(f"  2. Replace {_amber(str(target / 'logo.svg'))} with the real logo.")
    print("  3. Drop the folder (or a .zip of it) into your install's data dir under packs/,")
    print("     then open the Modules page > Partner Packs, click Rescan, and Apply.")


def cmd_pack(args: argparse.Namespace) -> None:
    """Dispatch ``pack`` sub-actions; print help when none is given."""
    action = getattr(args, "pack_action", None)
    if action == "new":
        cmd_pack_new(args)
    else:
        args._pack_parser.print_help()


# ── Arg parser ────────────────────────────────────────────────────────────
def _add_common_server_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    _add_data_dir_arg(p)
    p.add_argument(
        "--embedded-pg",
        action="store_true",
        help="Run an in-process PostgreSQL (no Docker); data in <data-dir>/pgdata (this is the default)",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the full command line, every subcommand included.

    Split out of :func:`main` so the parser can be inspected without running a
    command: ``test_cli_data_dir_is_declared_and_resolved_in_one_place`` walks
    every declaration here and fails if one of them names a path that is not
    absolute.

    Returns:
        The top-level parser, with all subparsers attached.
    """
    parser = argparse.ArgumentParser(
        prog="openconstructionerp",
        description=(
            "OpenConstructionERP, open-source construction cost estimation platform.\n\n"
            "Quick start, one command does everything:\n"
            "    openconstructionerp\n\n"
            "It creates the local database, loads the demo data, starts the server\n"
            "and opens http://127.0.0.1:8080 (demo@openconstructionerp.com / DemoPass1234!)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # ``--version`` as a top-level flag, because that is what a reader types
    # before they know the tool has subcommands at all, and it answered with an
    # argparse error and exit 2 for the whole life of the CLI.
    #
    # Two details are load-bearing. It stores a flag instead of using
    # ``action="version"`` so ``main`` can hand the work to :func:`cmd_version`
    # and the two spellings print one report from one implementation. And it
    # names its own dest: the ``upgrade`` subcommand declares a ``--version`` of
    # its own for pinning a release, and a subparser parses into a fresh
    # namespace whose every key is then copied onto this one, so sharing the
    # dest would make ``upgrade --version 2.6.10`` print a version report and
    # never upgrade anything. ``-V`` is free; ``-h`` is the only other short
    # option this parser declares.
    parser.add_argument(
        "-V",
        "--version",
        dest="show_version",
        action="store_true",
        help="Show version information and exit (same report as the 'version' command)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start the OpenConstructionERP server")
    _add_common_server_args(serve_p)
    serve_p.add_argument("--open", action="store_true", help="Open browser after startup")
    serve_p.add_argument("--quiet", action="store_true", help="Suppress banner and info logs")
    demo_group = serve_p.add_mutually_exclusive_group()
    demo_group.add_argument(
        "--no-demo",
        action="store_true",
        help=(
            "Start without demo accounts and showcase projects (sets SEED_DEMO=false "
            "and persists the choice to <data-dir>/demo_seed_choice.json so later "
            "starts stay clean too)"
        ),
    )
    demo_group.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Force demo accounts and showcase projects on and clear any earlier "
            "opt-out saved in <data-dir>/demo_seed_choice.json (from --no-demo, a "
            "'no' answer on first run, or removing demo data in the app), so the "
            "demo sign-in comes back"
        ),
    )

    # init-db (canonical) + init (alias for backward compat)
    init_db_p = subparsers.add_parser(
        "init-db",
        help="Create the database schema and data directories",
    )
    _add_data_dir_arg(init_db_p)
    init_db_p.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing embedded database cluster (and any legacy SQLite file) before init",
    )
    # Legacy alias - same args, same handler.
    init_p = subparsers.add_parser("init", help="Alias for init-db")
    _add_data_dir_arg(init_p)
    init_p.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing embedded database cluster (and any legacy SQLite file) before init",
    )

    # doctor
    doctor_p = subparsers.add_parser("doctor", help="Run installation health checks")
    _add_common_server_args(doctor_p)

    # version
    subparsers.add_parser("version", help="Show version information")

    # upgrade - pip-upgrade in *this* interpreter's env (Issue #96)
    upgrade_p = subparsers.add_parser(
        "upgrade",
        help="Upgrade openconstructionerp in the same env this command runs in",
    )
    upgrade_p.add_argument(
        "--version",
        default=None,
        help="Pin to a specific version (e.g. --version 2.6.10). Defaults to latest.",
    )
    # cmd_upgrade refuses to replace files a running cluster is executing from,
    # and it looks for that cluster in the data directory. Without this flag the
    # only data directory it could look in was the default one, so an operator
    # who keeps their data elsewhere was told nothing was running.
    _add_data_dir_arg(upgrade_p)

    # welcome (zero-network greeting + quick-start + support links)
    subparsers.add_parser(
        "welcome",
        help="Print a welcome screen with quick-start commands and support links",
    )
    subparsers.add_parser(
        "hello",
        help="Alias for 'welcome'",
    )

    # seed
    seed_p = subparsers.add_parser("seed", help="Load seed/demo data")
    seed_p.add_argument("--demo", action="store_true", help="Install demo project with sample data")
    _add_data_dir_arg(seed_p)

    # module - install / list / uninstall business modules
    module_p = subparsers.add_parser(
        "module",
        help="Install, list, or uninstall modules",
        description=(
            "Manage OpenConstructionERP modules.\n\n"
            "    openconstructionerp module install <archive.zip> [--force]\n"
            "    openconstructionerp module list\n"
            "    openconstructionerp module uninstall <name> [--force]\n\n"
            "A module is a Python package with a manifest.py. Install extracts it\n"
            "into the modules directory; restart the server to load it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    module_sub = module_p.add_subparsers(dest="module_action")

    module_install_p = module_sub.add_parser("install", help="Install a module from a .zip archive")
    module_install_p.add_argument("zip", help="Path to the module .zip archive")
    module_install_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing module of the same name",
    )

    module_sub.add_parser("list", help="List discovered modules (name, version, status)")

    module_uninstall_p = module_sub.add_parser("uninstall", help="Remove an installed module")
    module_uninstall_p.add_argument("name", help="Module name (oe_foo) or directory name (foo)")
    module_uninstall_p.add_argument(
        "--force",
        action="store_true",
        help="Remove even core / auto-install modules",
    )

    # pack - scaffold a new declarative partner pack
    pack_p = subparsers.add_parser(
        "pack",
        help="Scaffold and manage partner packs",
        description=(
            "Manage OpenConstructionERP partner packs (declarative preset bundles).\n\n"
            "    openconstructionerp pack new <slug> [--out DIR] [--force]\n\n"
            "Emits a minimal, valid pack folder (manifest.json + logo + onboarding\n"
            "+ README). Drop the folder (or a .zip of it) into <data-dir>/packs/ and\n"
            "activate it from the Modules page."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pack_sub = pack_p.add_subparsers(dest="pack_action")
    pack_new_p = pack_sub.add_parser("new", help="Scaffold a new partner pack folder")
    pack_new_p.add_argument("slug", help="Pack slug (lowercase, e.g. acme-de)")
    pack_new_p.add_argument(
        "--out",
        default=None,
        help="Parent directory to create the pack folder in (default: current directory)",
    )
    pack_new_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing folder of the same slug",
    )

    # Make each group's own parser reachable from its command so it can print
    # help when invoked with no sub-action (``openconstructionerp module``).
    module_p.set_defaults(_module_parser=module_p)
    pack_p.set_defaults(_pack_parser=pack_p)

    return parser


def main() -> None:
    """CLI entry point."""
    # Before the parser is built, because the command lines this answers are
    # not commands and argparse rejects them. See the block near the top.
    _answer_multiprocessing_re_execution()

    parser = _build_parser()
    args = parser.parse_args()

    # Answered before the command is looked at, because the case that was
    # broken is the one with no command at all: it falls through to the bare
    # invocation branch at the bottom, which starts a server.
    if getattr(args, "show_version", False):
        cmd_version(args)
        return

    # Embedded PostgreSQL is the default (see embedded_pg.is_requested). The
    # flag is an explicit override mapped to the same env var _setup_env reads
    # before any app module (and therefore the engine) is imported:
    #   --embedded-pg -> OE_USE_EMBEDDED_PG=1 (explicit; already the default)
    if getattr(args, "embedded_pg", False):
        os.environ["OE_USE_EMBEDDED_PG"] = "1"

    if args.command == "serve":
        cmd_serve(args)
    elif args.command in ("init-db", "init"):
        cmd_init_db(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "version":
        cmd_version(args)
    elif args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command == "module":
        cmd_module(args)
    elif args.command == "pack":
        cmd_pack(args)
    elif args.command in ("welcome", "hello"):
        cmd_welcome(args)
    elif args.command is None:
        # Default behaviour for bare ``openconstructionerp``:
        # * First run (no data dir yet) - show the welcome screen and an
        #   interactive "open in browser?" prompt so the user sees the URL,
        #   demo login and community links BEFORE uvicorn eats the
        #   terminal for the startup wait.
        # * Subsequent runs - jump straight to serve (they already know).
        args.host = DEFAULT_HOST
        args.port = DEFAULT_PORT
        args.quiet = False
        # The bare command declares no flags, so this reads the same default
        # every subcommand reads, through the same resolver.
        data_dir = _data_dir_from_args(args)
        # A first run is a data directory with no database behind it. This asked
        # only whether the legacy SQLite file was missing, and embedded
        # PostgreSQL replaced that file as the default in v6.0.0, so it is
        # absent on every install made since and the answer was always yes. A
        # workspace in daily use was greeted as a brand new one and re-prompted
        # on every bare invocation, which is the sort of defect that reads as
        # cosmetic until you notice the product cannot tell whether it has met
        # you before. The cluster marker is the test the demo-seed question a
        # few lines below already used; keeping both meant one question asked
        # two ways, and the way that decided the greeting was the wrong one.
        first_run = not data_dir.exists() or (
            not (data_dir / "pgdata" / "PG_VERSION").exists() and not (data_dir / "openestimate.db").exists()
        )

        if first_run:
            print_welcome(next_command_hint=False)
            url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
            # First-run demo choice: ask once on a genuinely fresh install
            # (no embedded cluster initialised yet, no legacy SQLite file)
            # when SEED_DEMO is not already forced via the environment and
            # no earlier answer is on record. The answer is persisted to
            # <data-dir>/demo_seed_choice.json so every later boot (and the
            # flagship/Heilbronn backfills) respects it.
            from app.core.demo_seed import read_demo_seed_choice, write_demo_seed_choice

            # Reaching here means first_run above already answered this, and
            # answering it twice is how the two drifted apart in the first
            # place.
            if "SEED_DEMO" not in os.environ and read_demo_seed_choice(data_dir) is None:
                seed_choice = _prompt_seed_demo()
                if seed_choice is not None:
                    write_demo_seed_choice(seed_choice, data_dir)
                    if not seed_choice:
                        os.environ["SEED_DEMO"] = "false"
            # Press 'o' (or Enter) to let the server open the browser
            # after it has bound the socket; any other answer keeps the
            # terminal focused (useful for SSH sessions).
            args.open = _prompt_open_browser(url, default_open=True)
            print()
            print(
                _dim(
                    _u(
                        "  Starting the server now \u2014 press Ctrl+C to stop.",
                        "  Starting the server now - press Ctrl+C to stop.",
                    ),
                ),
            )
            print()
        else:
            args.open = True
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
